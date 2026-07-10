from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from krystal_quorum.approval import ApprovalCommitment, ApprovalReceipt
from krystal_quorum.commitments import Commitment, CommitmentCategory
from krystal_quorum.diff_models import (
    DIFF_CLAUSE_IDS,
    AggregatedCoverageItem,
    CoverageStatus,
    DiffChangedFile,
    DiffEvidenceFile,
    DiffManifest,
    DiffResult,
    DiffReviewerOutput,
    GitManifest,
    PlanManifest,
    PlanProvenance,
    QuorumHealth,
    QuorumMetrics,
)
from krystal_quorum.diff_persist import persist_diff_run
from krystal_quorum.models import ClauseStatus, ReviewIssue, Verdict
from krystal_quorum.persist import PersistenceError
from krystal_quorum.reviewer_specs import DataBoundary, ReviewerSpec


DIGEST = "a" * 64
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
PLAN_TEXT = "## Acceptance Criteria\n- [AC-1] Ship the implementation.\n"
PATCH_TEXT = "diff --git a/app.py b/app.py\n+implemented = True\n"
REVIEW_INPUT = '{"review_kind":"diff"}'


def _reviewer_spec(reviewer_id: str = "mock") -> ReviewerSpec:
    return ReviewerSpec(
        reviewer_id=reviewer_id,
        backend="mock",
        family="mock-family",
        endpoint=None,
        data_boundary=DataBoundary.LOCAL,
    )


def _approval() -> ApprovalReceipt:
    return ApprovalReceipt(
        schema_version="krystal-quorum.approval.v1",
        tool_version="0.7.0",
        created_at="2026-07-10T00:00:00Z",
        authenticity="unsigned",
        verdict="APPROVE",
        plan_path="plan.md",
        plan_sha256=DIGEST,
        base_ref="HEAD",
        base_sha=BASE_SHA,
        reviewers_used=["mock"],
        reviewer_families=["mock-family"],
        diversity="ok",
        reconciled_sha256="b" * 64,
        commitments=[
            ApprovalCommitment(
                id="AC-1",
                category=CommitmentCategory.ACCEPTANCE,
                text="Ship the implementation.",
                source_line=2,
            )
        ],
    )


def _reviewer_output(
    reviewer: str,
    round_number: int,
    *,
    abstain: bool = False,
) -> DiffReviewerOutput:
    return DiffReviewerOutput(
        reviewer=reviewer,
        round=round_number,
        verdict=Verdict.ABSTAIN if abstain else Verdict.APPROVE,
        confidence=0.0 if abstain else 0.9,
        commitment_coverage=[] if abstain else [
            {
                "commitment_id": "AC-1",
                "status": "IMPLEMENTED",
                "claim": "The implementation is present.",
                "evidence": "app.py:1",
                "path": "app.py",
                "line_start": 1,
            }
        ],
        scope_findings=[],
        blocking_issues=[
            ReviewIssue(
                id="runtime-1",
                section="runtime",
                claim="reviewer transport failed",
                evidence="RuntimeError",
            )
        ] if abstain else [],
        suggestions=[],
        per_clause={
            clause: ClauseStatus.UNCLEAR if abstain else ClauseStatus.SATISFIED
            for clause in DIFF_CLAUSE_IDS
        },
        raw_response="",
        elapsed_seconds=0.01,
    )


def _executed(tmp_path: Path) -> SimpleNamespace:
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(PLAN_TEXT, encoding="utf-8")
    evidence_files = (
        DiffEvidenceFile(
            status="M",
            path="app.py",
            old_path=None,
            kind="text",
            source="working_tree",
        ),
    )
    result = DiffResult(
        schema_version="krystal-quorum.diff.v1",
        review_kind="diff",
        verdict=Verdict.APPROVE,
        plan_provenance=PlanProvenance.UNVERIFIED_REFERENCE,
        plan=PlanManifest(path="plan.md", sha256=DIGEST, approval_sha256=None),
        git=GitManifest(
            base_ref="main",
            base_sha=BASE_SHA,
            head_ref=None,
            head_sha=HEAD_SHA,
            merge_base_sha=None,
            working_tree=True,
        ),
        diff=DiffManifest(
            sha256=hashlib.sha256(PATCH_TEXT.encode("utf-8")).hexdigest(),
            changed_files=[DiffChangedFile(status="M", path="app.py", old_path=None)],
        ),
        review_input_sha256=hashlib.sha256(REVIEW_INPUT.encode("utf-8")).hexdigest(),
        quorum=QuorumMetrics(
            health="healthy",
            usable_reviewers=1,
            total_reviewers=1,
            distinct_families=1,
            agreement_ratio=1.0,
            contradiction_count=0,
        ),
        reviewers_used=["mock"],
        coverage=[
            AggregatedCoverageItem(
                commitment_id="AC-1",
                status=CoverageStatus.IMPLEMENTED,
                corroborated=False,
                reviewers=["mock"],
                evidence=["app.py:1"],
            )
        ],
        scope_findings=[],
        unresolved_for_human=[],
        output_dir=str(tmp_path / "preflight-placeholder"),
    )
    prepared = SimpleNamespace(
        options=SimpleNamespace(out_dir=tmp_path / "reviews"),
        plan_path=plan_path,
        plan_text=PLAN_TEXT,
        approval_receipt=None,
        snapshot=SimpleNamespace(patch=PATCH_TEXT),
        evidence_files=evidence_files,
        review_input=REVIEW_INPUT,
        reviewer_specs=(_reviewer_spec(),),
        diversity=SimpleNamespace(status="ok", reason="distinct reviewer families"),
        commitments=(
            Commitment(
                id="AC-1",
                category=CommitmentCategory.ACCEPTANCE,
                text="Ship the implementation.",
                source_line=2,
                group=None,
            ),
        ),
    )
    return SimpleNamespace(
        prepared=prepared,
        round1_outputs=(),
        round2_outputs=(),
        result=result,
    )


def test_persist_diff_run_writes_exact_standalone_artifacts_and_hashes(
    tmp_path: Path,
) -> None:
    executed = _executed(tmp_path)
    run_dir, result = persist_diff_run(executed)

    assert result.output_dir == str(run_dir)
    assert "preflight-placeholder" not in result.output_dir
    assert {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()} == {
        "changed_files.json",
        "coverage.json",
        "diff_input.patch",
        "diff_input.sha256",
        "manifest.json",
        "plan_input.md",
        "plan_input.sha256",
        "reconciled.json",
        "review_input.md",
        "review_input.sha256",
        "summary.md",
    }
    assert not (run_dir / "approval.json").exists()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        payload = (run_dir / artifact["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]
    assert json.loads((run_dir / "reconciled.json").read_text(encoding="utf-8"))[
        "output_dir"
    ] == str(run_dir)
    assert json.loads((run_dir / "changed_files.json").read_text(encoding="utf-8")) == [
        item.model_dump(mode="json") for item in executed.prepared.evidence_files
    ]


def test_verified_empty_diff_writes_approval_and_truthful_complete_summary(
    tmp_path: Path,
) -> None:
    executed = _executed(tmp_path)
    executed.prepared.approval_receipt = _approval()
    executed.prepared.snapshot.patch = ""
    executed.prepared.evidence_files = ()
    executed.result = executed.result.model_copy(
        update={
            "verdict": Verdict.REVISE,
            "plan_provenance": PlanProvenance.VERIFIED_RECEIPT,
            "plan": executed.result.plan.model_copy(update={"approval_sha256": "c" * 64}),
            "diff": DiffManifest(
                sha256=hashlib.sha256(b"").hexdigest(),
                changed_files=[],
            ),
            "quorum": QuorumMetrics(
                health="collapsed",
                usable_reviewers=0,
                total_reviewers=1,
                distinct_families=0,
                agreement_ratio=0.0,
                contradiction_count=0,
            ),
            "coverage": [
                AggregatedCoverageItem(
                    commitment_id="AC-1",
                    status=CoverageStatus.NOT_EVIDENT,
                    corroborated=False,
                    reviewers=[],
                    evidence=[],
                )
            ],
            "unresolved_for_human": ["No implementation diff was present."],
        }
    )

    run_dir, _ = persist_diff_run(executed)

    assert (run_dir / "approval.json").read_text(encoding="utf-8").endswith("\n")
    assert not (run_dir / "round1").exists()
    assert not (run_dir / "round2").exists()
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    required_in_order = (
        "Verdict: **REVISE**",
        "Plan provenance: `verified_receipt`",
        "## Git Baseline",
        BASE_SHA,
        HEAD_SHA,
        "## Quorum And Diversity",
        "collapsed",
        "## Commitment Coverage",
        "AC-1",
        "NOT_EVIDENT",
        "not present in diff",
        "## Unplanned Scope Findings",
        "## Abstentions And Contradictions",
        "## Human Triage",
        "No implementation diff was present.",
        "## Artifacts",
        str(run_dir),
    )
    positions = [summary.index(value) for value in required_in_order]
    assert positions == sorted(positions)


def test_reviewer_runtime_outputs_use_sanitized_names_and_manifest_metadata(
    tmp_path: Path,
) -> None:
    executed = _executed(tmp_path)
    reviewer_ids = ("command:CON/../../unsafe", "command:CON\\..\\..\\unsafe")
    executed.prepared.reviewer_specs = tuple(_reviewer_spec(item) for item in reviewer_ids)
    executed.round1_outputs = tuple(
        _reviewer_output(item, 1, abstain=index == 0)
        for index, item in enumerate(reviewer_ids)
    )
    executed.round2_outputs = tuple(_reviewer_output(item, 2) for item in reviewer_ids)
    executed.result = executed.result.model_copy(
        update={
            "verdict": Verdict.REVISE,
            "reviewers_used": list(reviewer_ids),
            "quorum": executed.result.quorum.model_copy(
                update={
                    "health": QuorumHealth.DEGRADED,
                    "usable_reviewers": 1,
                    "total_reviewers": 2,
                }
            ),
        }
    )

    run_dir, _ = persist_diff_run(executed)

    round1_files = list((run_dir / "round1").glob("*.json"))
    round2_files = list((run_dir / "round2").glob("*.json"))
    assert len(round1_files) == len(round2_files) == 2
    assert len({path.name for path in round1_files}) == 2
    assert all(path.parent == run_dir / "round1" for path in round1_files)
    assert all(path.parent == run_dir / "round2" for path in round2_files)
    assert all(".." not in path.name for path in (*round1_files, *round2_files))
    assert all("/" not in path.name and "\\" not in path.name for path in round1_files)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["reviewers_used"] == list(reviewer_ids)
    assert manifest["reviewer_families"] == ["mock-family", "mock-family"]
    assert manifest["data_boundaries"] == {
        reviewer_id: "local" for reviewer_id in reviewer_ids
    }
    assert any(item["path"].startswith("round1/") for item in manifest["artifacts"])
    assert any(item["path"].startswith("round2/") for item in manifest["artifacts"])
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert reviewer_ids[0] in summary


def test_every_artifact_is_atomically_replaced_from_a_same_directory_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def record_replace(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        replacements.append((source_path, destination_path))
        real_replace(source_path, destination_path)

    monkeypatch.setattr(os, "replace", record_replace)

    run_dir, _ = persist_diff_run(_executed(tmp_path))

    persisted = {path for path in run_dir.rglob("*") if path.is_file()}
    replaced = {destination for _, destination in replacements}
    assert replaced == persisted
    assert run_dir / "manifest.json" in replaced
    assert all(source.parent == destination.parent for source, destination in replacements)
    assert all(source.name.endswith(".tmp") for source, _ in replacements)
    assert not list(run_dir.rglob("*.tmp"))


def test_persistence_error_reports_partial_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_replace = os.replace

    def fail_manifest(source: str | Path, destination: str | Path) -> None:
        if Path(destination).name == "manifest.json":
            raise OSError("disk full")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_manifest)

    with pytest.raises(PersistenceError, match="diff review artifacts") as caught:
        persist_diff_run(_executed(tmp_path))

    assert caught.value.partial_path is not None
    assert caught.value.partial_path.is_dir()
    assert not (caught.value.partial_path / "manifest.json").exists()
    assert not list(caught.value.partial_path.rglob("*.tmp"))
