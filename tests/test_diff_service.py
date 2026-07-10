from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from krystal_quorum.approval import (
    ApprovalCommitment,
    ApprovalReceipt,
    canonical_json_sha256,
)
from krystal_quorum.commitments import CommitmentCategory
from krystal_quorum.diff_models import (
    DIFF_CLAUSE_IDS,
    CoverageStatus,
    DiffCoverageItem,
    DiffEvidenceFile,
    DiffReviewerOutput,
    PlanProvenance,
)
from krystal_quorum.diff_service import (
    DEFAULT_MAX_PLAN_CHARS,
    DEFAULT_MAX_REVIEW_CHARS,
    DiffRunOptions,
    DiffServiceError,
    execute_diff_run,
    prepare_diff_run,
)
from krystal_quorum.diffing import ChangedFile, DiffSnapshot
from krystal_quorum.models import ClauseStatus, Verdict
from krystal_quorum.reviewer_specs import DataBoundary, ReviewerSpec


PLAN_TEXT = "## Acceptance Criteria\n- [AC-1] Ship the implementation safely.\n"
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40


def _write_plan(tmp_path: Path, text: str = PLAN_TEXT) -> Path:
    plan = tmp_path / "plan.md"
    plan.write_text(text, encoding="utf-8")
    return plan


def _snapshot(
    *,
    patch: str = "diff --git a/app.py b/app.py\n+implemented = True\n",
    source: str = "working_tree",
) -> DiffSnapshot:
    changed_files = (
        (
            ChangedFile(
                status="A",
                path="app.py",
                source=source,
                kind="text",
            ),
        )
        if patch
        else ()
    )
    return DiffSnapshot(
        repo_root=Path.cwd(),
        base_ref="main",
        head_ref=None,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        merge_base_sha=None,
        provenance="standalone",
        comparison="working_tree",
        include_untracked=True,
        changed_files=changed_files,
        working_tree_status=(),
        patch=patch,
        diff_sha256=hashlib.sha256(patch.encode("utf-8")).hexdigest(),
    )


def _options(plan: Path, **changes: Any) -> DiffRunOptions:
    options = DiffRunOptions(plan=plan, repo=plan.parent, base="main")
    return replace(options, **changes)


def _patch_capture(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: DiffSnapshot,
) -> None:
    monkeypatch.setattr(
        "krystal_quorum.diff_service.capture_diff",
        lambda *args, **kwargs: snapshot,
    )


def _explode(message: str):
    def explode(*args, **kwargs):
        raise AssertionError(message)

    return explode


def _receipt(plan: Path) -> ApprovalReceipt:
    return ApprovalReceipt(
        schema_version="krystal-quorum.approval.v1",
        tool_version="0.7.0",
        created_at="2026-07-10T00:00:00Z",
        authenticity="unsigned",
        verdict="APPROVE",
        plan_path=plan.name,
        plan_sha256=hashlib.sha256(PLAN_TEXT.encode("utf-8")).hexdigest(),
        base_ref="HEAD",
        base_sha=BASE_SHA,
        reviewers_used=["mock"],
        reviewer_families=["mock"],
        diversity="ok",
        reconciled_sha256="3" * 64,
        commitments=[
            ApprovalCommitment(
                id="AC-1",
                category=CommitmentCategory.ACCEPTANCE,
                text="Ship the implementation safely.",
                source_line=2,
            )
        ],
    )


def _local_spec(reviewer_id: str = "mock") -> ReviewerSpec:
    return ReviewerSpec(
        reviewer_id=reviewer_id,
        backend="mock",
        family=reviewer_id,
        endpoint=None,
        data_boundary=DataBoundary.LOCAL,
    )


def _external_spec() -> ReviewerSpec:
    return ReviewerSpec(
        reviewer_id="openai:test-model",
        backend="openai",
        family="test-model",
        endpoint="https://example.test/v1",
        data_boundary=DataBoundary.EXTERNAL,
        model="test-model",
    )


def _implemented_output(reviewer: str, round_number: int) -> DiffReviewerOutput:
    return DiffReviewerOutput(
        reviewer=reviewer,
        round=round_number,
        verdict=Verdict.APPROVE,
        confidence=0.9,
        commitment_coverage=[
            DiffCoverageItem(
                commitment_id="AC-1",
                status=CoverageStatus.IMPLEMENTED,
                claim="The implementation is present.",
                evidence="app.py:1",
                path="app.py",
                line_start=1,
            )
        ],
        scope_findings=[],
        blocking_issues=[],
        suggestions=[],
        per_clause={clause_id: ClauseStatus.SATISFIED for clause_id in DIFF_CLAUSE_IDS},
        raw_response="synthetic",
        elapsed_seconds=0.01,
    )


def test_options_expose_approved_defaults(tmp_path: Path) -> None:
    options = DiffRunOptions(plan=_write_plan(tmp_path))

    assert options.max_plan_chars == DEFAULT_MAX_PLAN_CHARS == 120_000
    assert options.max_diff_chars == 160_000
    assert options.max_review_chars == DEFAULT_MAX_REVIEW_CHARS == 220_000
    assert options.context_lines == 20
    assert options.include_untracked is True
    assert options.round2 is False
    assert options.dry_run is False


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"max_plan_chars": -1}, "max_plan_chars"),
        ({"max_diff_chars": 0}, "max_diff_chars"),
        ({"max_review_chars": 0}, "max_review_chars"),
        ({"context_lines": -1}, "context_lines"),
        ({"context_lines": 201}, "context_lines"),
    ],
)
def test_invalid_bounds_fail_before_plan_or_git_or_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, int],
    message: str,
) -> None:
    plan = _write_plan(tmp_path)
    monkeypatch.setattr("krystal_quorum.diff_service.capture_diff", _explode("git ran"))
    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        _explode("client constructed"),
    )

    with pytest.raises(DiffServiceError, match=message):
        prepare_diff_run(_options(plan, **changes))


def test_plan_limit_zero_disables_only_the_plan_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path, PLAN_TEXT + ("x" * 200))
    _patch_capture(monkeypatch, _snapshot())

    prepared = prepare_diff_run(_options(plan, max_plan_chars=0))

    assert prepared.plan_text.endswith("x" * 200)


def test_positive_plan_limit_reports_actual_chars_before_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    monkeypatch.setattr("krystal_quorum.diff_service.capture_diff", _explode("git ran"))

    with pytest.raises(DiffServiceError, match=r"actual_chars=64; limit=10; rough_tokens=16"):
        prepare_diff_run(_options(plan, max_plan_chars=10))


def test_cli_mode_combinations_fail_before_plan_or_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    approval = tmp_path / "approval.json"
    monkeypatch.setattr("krystal_quorum.diff_service.capture_diff", _explode("git ran"))

    with pytest.raises(DiffServiceError, match="approval.*base"):
        prepare_diff_run(_options(plan, approval=approval))
    with pytest.raises(DiffServiceError, match="requires base"):
        prepare_diff_run(_options(plan, base=None))


def test_no_commitments_fail_before_approval_git_or_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path, "# Notes\nNothing required.\n")
    monkeypatch.setattr(
        "krystal_quorum.diff_service.load_and_validate_approval",
        _explode("approval loaded"),
    )
    monkeypatch.setattr("krystal_quorum.diff_service.capture_diff", _explode("git ran"))
    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        _explode("client constructed"),
    )

    with pytest.raises(DiffServiceError, match="no required commitments"):
        prepare_diff_run(
            _options(plan, approval=tmp_path / "approval.json", base=None)
        )


def test_invalid_approval_stops_before_git_and_reviewer_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    monkeypatch.setattr(
        "krystal_quorum.diff_service.load_and_validate_approval",
        _explode("invalid receipt and sibling reconciliation"),
    )
    monkeypatch.setattr("krystal_quorum.diff_service.capture_diff", _explode("git ran"))
    monkeypatch.setattr(
        "krystal_quorum.diff_service.parse_reviewer_specs",
        _explode("reviewer specs parsed"),
    )

    with pytest.raises(AssertionError, match="invalid receipt"):
        prepare_diff_run(
            _options(plan, approval=tmp_path / "approval.json", base=None)
        )


def test_verified_receipt_baseline_is_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    receipt = _receipt(plan)
    captured: dict[str, Any] = {}

    def load_approval(*args, **kwargs):
        captured["approval_head"] = kwargs["head_sha"]
        return receipt

    def capture(*args, **kwargs):
        captured.update(kwargs)
        return _snapshot().model_copy(
            update={"base_ref": BASE_SHA, "provenance": "verified"}
        )

    monkeypatch.setattr(
        "krystal_quorum.diff_service.load_and_validate_approval", load_approval
    )
    monkeypatch.setattr("krystal_quorum.diff_service.capture_diff", capture)

    prepared = prepare_diff_run(
        _options(
            plan,
            approval=tmp_path / "approval.json",
            base=None,
            head="feature-head",
        )
    )

    assert captured["approval_head"] == "feature-head"
    assert captured["base_ref"] == BASE_SHA
    assert captured["verified_base"] is True
    assert captured["head_ref"] == "feature-head"
    assert prepared.plan_provenance == PlanProvenance.VERIFIED_RECEIPT
    assert prepared.approval_receipt == receipt
    assert prepared.approval_sha256 == canonical_json_sha256(receipt)


def test_complete_input_is_deterministic_but_evidence_authority_stays_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    snapshot = _snapshot()
    _patch_capture(monkeypatch, snapshot)

    prepared = prepare_diff_run(_options(plan))
    payload = json.loads(prepared.review_input)

    assert payload["plan"]["text"] == PLAN_TEXT
    assert payload["commitments"][0]["id"] == "AC-1"
    assert payload["changed_files"] == [
        item.model_dump(mode="json") for item in prepared.evidence_files
    ]
    assert payload["git"]["base_sha"] == BASE_SHA
    assert payload["patch"] == snapshot.patch
    assert prepared.evidence_files == (
        DiffEvidenceFile(
            status="A",
            path="app.py",
            old_path=None,
            kind="text",
            source="working_tree",
        ),
    )
    assert prepared.review_input_sha256 == hashlib.sha256(
        prepared.review_input.encode("utf-8")
    ).hexdigest()


def test_complete_input_limit_is_independent_and_precedes_reviewer_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot())
    monkeypatch.setattr(
        "krystal_quorum.diff_service.parse_reviewer_specs",
        _explode("reviewer specs parsed"),
    )

    with pytest.raises(
        DiffServiceError,
        match=r"Complete reviewer input exceeds max_review_chars: actual_chars=\d+; "
        r"limit=100; rough_tokens=\d+",
    ):
        prepare_diff_run(_options(plan, max_review_chars=100))


def test_hosted_and_unknown_boundaries_fail_before_client_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot())
    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        _explode("client constructed"),
    )

    with pytest.raises(DiffServiceError, match="hosted.*unsupported"):
        prepare_diff_run(_options(plan, reviewers="hosted:test"))

    unknown = ReviewerSpec(
        reviewer_id="command:unsafe",
        backend="command",
        family="unsafe",
        endpoint=None,
        data_boundary=DataBoundary.UNKNOWN,
        command=("must-not-run",),
    )
    monkeypatch.setattr(
        "krystal_quorum.diff_service.parse_reviewer_specs",
        lambda *args, **kwargs: [unknown],
    )
    with pytest.raises(DiffServiceError, match="unknown data boundary.*command:unsafe"):
        prepare_diff_run(_options(plan, reviewers="command:unsafe"))


def test_required_diversity_fails_before_client_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot())
    specs = [
        ReviewerSpec(
            reviewer_id=f"openai:same-{index}",
            backend="openai",
            family="same",
            endpoint="https://example.test/v1",
            data_boundary=DataBoundary.EXTERNAL,
            model=f"same-{index}",
        )
        for index in range(2)
    ]
    monkeypatch.setattr(
        "krystal_quorum.diff_service.parse_reviewer_specs",
        lambda *args, **kwargs: specs,
    )
    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        _explode("client constructed"),
    )

    with pytest.raises(DiffServiceError, match="reviewer diversity"):
        prepare_diff_run(
            _options(plan, reviewers="ignored", require_diversity=True)
        )


def test_external_secrets_require_opt_in_while_local_runs_warn_without_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "SERVICE_API_KEY=abcdefghijklmnop"
    plan = _write_plan(tmp_path, PLAN_TEXT + f"\n```text\n{secret}\n```\n")
    _patch_capture(monkeypatch, _snapshot())
    monkeypatch.setattr(
        "krystal_quorum.diff_service.parse_reviewer_specs",
        lambda *args, **kwargs: [_external_spec()],
    )

    with pytest.raises(DiffServiceError, match="allow_secret_looking_input"):
        prepare_diff_run(_options(plan, reviewers="ignored"))

    external = prepare_diff_run(
        _options(
            plan,
            reviewers="ignored",
            allow_secret_looking_input=True,
        )
    )
    assert external.secret_warning_counts == {"sensitive-assignment": 1}
    assert external.external_destinations == ("openai:test-model",)

    monkeypatch.setattr(
        "krystal_quorum.diff_service.parse_reviewer_specs",
        lambda *args, **kwargs: [_local_spec()],
    )
    local = prepare_diff_run(_options(plan, reviewers="ignored"))
    assert local.secret_warning_classes == ("sensitive-assignment",)
    assert secret not in repr(local.dry_run_metadata)


def test_external_untracked_content_requires_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot(source="untracked"))
    monkeypatch.setattr(
        "krystal_quorum.diff_service.parse_reviewer_specs",
        lambda *args, **kwargs: [_external_spec()],
    )

    with pytest.raises(DiffServiceError, match="allow_untracked_external"):
        prepare_diff_run(
            _options(
                plan,
                reviewers="ignored",
                allow_secret_looking_input=True,
            )
        )

    prepared = prepare_diff_run(
        _options(
            plan,
            reviewers="ignored",
            allow_secret_looking_input=True,
            allow_untracked_external=True,
        )
    )
    assert prepared.captured_untracked is True


def test_prepare_and_dry_run_never_construct_clients_or_create_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    out_dir = tmp_path / "reviews"
    _patch_capture(monkeypatch, _snapshot())
    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        _explode("client constructed"),
    )

    prepared = prepare_diff_run(
        _options(plan, dry_run=True, out_dir=out_dir)
    )

    assert prepared.dry_run_metadata.plan_sha256 == prepared.plan_sha256
    assert prepared.dry_run_metadata.diff_sha256 == prepared.snapshot.diff_sha256
    assert prepared.dry_run_metadata.changed_file_count == 1
    assert prepared.dry_run_metadata.destinations == ("mock",)
    assert not out_dir.exists()


@pytest.mark.asyncio
async def test_execute_rejects_dry_run_without_constructing_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot())
    prepared = prepare_diff_run(_options(plan, dry_run=True))
    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        _explode("client constructed"),
    )

    with pytest.raises(DiffServiceError, match="dry-run"):
        await execute_diff_run(prepared)


@pytest.mark.asyncio
async def test_empty_diff_revises_every_commitment_without_reviewer_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot(patch=""))
    prepared = prepare_diff_run(_options(plan))
    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        _explode("client constructed"),
    )

    executed = await execute_diff_run(prepared)

    assert executed.round1_outputs == ()
    assert executed.round2_outputs == ()
    assert executed.result.verdict == Verdict.REVISE
    assert [item.status for item in executed.result.coverage] == [
        CoverageStatus.NOT_EVIDENT
    ]
    assert executed.result.quorum.health.value == "collapsed"


@pytest.mark.asyncio
async def test_transport_failure_becomes_auditable_abstention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot())
    prepared = prepare_diff_run(_options(plan))

    class FailingReviewer:
        id = "mock"

        async def review_diff_round1(self, *args, **kwargs):
            raise RuntimeError("synthetic transport failure")

    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        lambda specs: [FailingReviewer()],
    )

    executed = await execute_diff_run(prepared)

    assert len(executed.round1_outputs) == 1
    assert executed.round1_outputs[0].verdict == Verdict.ABSTAIN
    assert executed.round1_outputs[0].blocking_issues[0].evidence == "RuntimeError"
    assert executed.result.verdict == Verdict.ABSTAIN
    assert executed.result.quorum.health.value == "collapsed"


@pytest.mark.asyncio
async def test_transport_abstention_never_exposes_exception_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot())
    prepared = prepare_diff_run(_options(plan))
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz"

    class FailingReviewer:
        id = "mock"

        async def review_diff_round1(self, *args, **kwargs):
            raise RuntimeError(f"request failed with {secret}")

    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        lambda specs: [FailingReviewer()],
    )

    executed = await execute_diff_run(prepared)

    evidence = executed.round1_outputs[0].blocking_issues[0].evidence
    assert evidence == "RuntimeError"
    assert secret not in evidence


@pytest.mark.asyncio
async def test_rounds_run_concurrently_and_round2_receives_round1_peer_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot())
    specs = [_local_spec("reviewer-a"), _local_spec("reviewer-b")]
    monkeypatch.setattr(
        "krystal_quorum.diff_service.parse_reviewer_specs",
        lambda *args, **kwargs: specs,
    )
    prepared = prepare_diff_run(
        _options(plan, reviewers="ignored", round2=True)
    )

    round1_started: list[str] = []
    round2_started: list[str] = []
    round1_release = asyncio.Event()
    round2_release = asyncio.Event()
    round2_peers: dict[str, tuple[str, ...]] = {}
    evidence_seen: dict[str, tuple[DiffEvidenceFile, ...]] = {}

    class ConcurrentReviewer:
        def __init__(self, reviewer_id: str) -> None:
            self.id = reviewer_id

        async def review_diff_round1(
            self, review_input, commitments, changed_files, *, timeout_s
        ):
            del review_input, commitments, timeout_s
            evidence_seen[f"{self.id}-1"] = tuple(changed_files)
            round1_started.append(self.id)
            if len(round1_started) == 2:
                round1_release.set()
            await round1_release.wait()
            return _implemented_output(self.id, 1)

        async def review_diff_round2(
            self,
            review_input,
            commitments,
            changed_files,
            round1_outputs,
            *,
            timeout_s,
        ):
            del review_input, commitments, timeout_s
            evidence_seen[f"{self.id}-2"] = tuple(changed_files)
            round2_peers[self.id] = tuple(output.reviewer for output in round1_outputs)
            round2_started.append(self.id)
            if len(round2_started) == 2:
                round2_release.set()
            await round2_release.wait()
            return _implemented_output(self.id, 2)

    reviewers = [ConcurrentReviewer(spec.reviewer_id) for spec in specs]
    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        lambda received: reviewers if received == specs else [],
    )

    executed = await asyncio.wait_for(execute_diff_run(prepared), timeout=1)

    assert set(round1_started) == {"reviewer-a", "reviewer-b"}
    assert set(round2_started) == {"reviewer-a", "reviewer-b"}
    assert round2_peers == {
        "reviewer-a": ("reviewer-a", "reviewer-b"),
        "reviewer-b": ("reviewer-a", "reviewer-b"),
    }
    assert all(files == prepared.evidence_files for files in evidence_seen.values())
    assert [output.round for output in executed.round1_outputs] == [1, 1]
    assert [output.round for output in executed.round2_outputs] == [2, 2]
    assert executed.result.verdict == Verdict.APPROVE


def test_standalone_provenance_and_safe_dry_run_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path)
    _patch_capture(monkeypatch, _snapshot())

    prepared = prepare_diff_run(_options(plan))

    assert prepared.plan_provenance == PlanProvenance.UNVERIFIED_REFERENCE
    assert prepared.approval_receipt is None
    assert prepared.approval_sha256 is None
    assert prepared.dry_run_metadata.review_input_chars == len(prepared.review_input)
    assert prepared.dry_run_metadata.review_input_rough_tokens == (
        len(prepared.review_input) + 3
    ) // 4
    assert prepared.dry_run_metadata.warning_classes == ()
    assert prepared.dry_run_metadata.warning_counts == {}
