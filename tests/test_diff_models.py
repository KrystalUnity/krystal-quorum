import json

import pytest
from pydantic import ValidationError

from krystal_quorum.commitments import Commitment, CommitmentCategory
from krystal_quorum.diff_models import (
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
    QuorumMetrics,
    ScopeCategory,
    ScopeFinding,
)
from krystal_quorum.models import ClauseStatus, ReviewIssue, Verdict
from krystal_quorum.reviewers.diff_base import (
    diff_fallback_output,
    expected_commitment_ids,
    parse_diff_reviewer_output,
)


DIFF_CLAUSES = {
    "scope.alignment": "SATISFIED",
    "tests.coverage": "SATISFIED",
    "security.alignment": "N/A",
    "dependencies.alignment": "N/A",
    "rollback.implemented": "N/A",
    "observability.implemented": "N/A",
}


def _commitment(commitment_id: str, text: str = "Implement the requested behavior.") -> Commitment:
    return Commitment(
        id=commitment_id,
        category=CommitmentCategory.ACCEPTANCE,
        text=text,
        source_line=10,
        group=None,
    )


def _payload(
    *coverage: dict[str, object], verdict: str = "APPROVE"
) -> dict[str, object]:
    return {
        "verdict": verdict,
        "confidence": 0.84,
        "commitment_coverage": list(coverage),
        "scope_findings": [],
        "blocking_issues": [],
        "suggestions": [],
        "per_clause": DIFF_CLAUSES,
    }


def _coverage(
    commitment_id: str,
    *,
    status: str = "IMPLEMENTED",
    path: str | None = "src/feature.py",
    line_start: int | None = 12,
) -> dict[str, object]:
    return {
        "commitment_id": commitment_id,
        "status": status,
        "claim": "The changed implementation covers this commitment.",
        "evidence": "src/feature.py:12" if path else None,
        "path": path,
        "line_start": line_start,
    }


def _parse(payload: dict[str, object], commitments: list[Commitment]) -> DiffReviewerOutput:
    return parse_diff_reviewer_output(
        "local",
        1,
        f"<json>{json.dumps(payload)}</json>",
        elapsed_seconds=0.2,
        retries=0,
        commitments=commitments,
        changed_files=[
            DiffEvidenceFile(
                status="M",
                path="src/feature.py",
                old_path=None,
                kind="text",
                source="tracked",
            ),
            DiffEvidenceFile(
                status="M",
                path="assets/logo.bin",
                old_path=None,
                kind="binary",
                source="tracked",
            ),
            DiffEvidenceFile(
                status="D",
                path="src/deleted.py",
                old_path=None,
                kind="text",
                source="tracked",
            ),
        ],
    )


def test_diff_reviewer_output_accepts_strict_valid_payload() -> None:
    output = _parse(_payload(_coverage("AC-1")), [_commitment("AC-1")])

    assert output.verdict == Verdict.APPROVE
    assert output.commitment_coverage[0].status == CoverageStatus.IMPLEMENTED
    assert output.per_clause["scope.alignment"] == ClauseStatus.SATISFIED


@pytest.mark.parametrize("status", ["IMPLEMENTED", "PARTIAL", "MISSING", "NOT_EVIDENT", "N/A"])
def test_coverage_status_accepts_only_exact_contract_values(status: str) -> None:
    item = _coverage("AC-1", status=status)
    if status in {"MISSING", "NOT_EVIDENT", "N/A"}:
        item.update(evidence=None, path=None, line_start=None)

    verdict = "APPROVE" if status == "IMPLEMENTED" else "REVISE"
    parsed = _parse(_payload(item, verdict=verdict), [_commitment("AC-1")])

    assert parsed.commitment_coverage[0].status.value == status


def test_coverage_status_rejects_case_drift() -> None:
    output = _parse(_payload(_coverage("AC-1", status="implemented")), [_commitment("AC-1")])

    assert output.verdict == Verdict.ABSTAIN


@pytest.mark.parametrize("status", ["MISSING", "NOT_EVIDENT"])
def test_absence_statuses_accept_truthful_null_evidence_locations(status: str) -> None:
    item = _coverage("AC-1", status=status, path=None, line_start=None)
    item["evidence"] = None

    output = _parse(_payload(item, verdict="REVISE"), [_commitment("AC-1")])

    assert output.commitment_coverage[0].path is None
    assert output.commitment_coverage[0].line_start is None
    assert output.commitment_coverage[0].evidence is None


@pytest.mark.parametrize(
    ("path", "evidence"),
    [("assets/logo.bin", "binary file changed"), ("src/deleted.py", "deleted file")],
)
def test_binary_and_deleted_evidence_accept_null_line(path: str, evidence: str) -> None:
    item = _coverage("AC-1", path=path, line_start=None)
    item["evidence"] = evidence

    output = _parse(_payload(item), [_commitment("AC-1")])

    assert output.commitment_coverage[0].path == path
    assert output.commitment_coverage[0].line_start is None


def test_line_number_requires_a_path() -> None:
    item = _coverage("AC-1", path=None, line_start=12)

    output = _parse(_payload(item), [_commitment("AC-1")])

    assert output.verdict == Verdict.ABSTAIN


def test_present_evidence_path_must_be_a_changed_file() -> None:
    item = _coverage("AC-1", path="src/unchanged.py", line_start=4)

    output = _parse(_payload(item), [_commitment("AC-1")])

    assert output.verdict == Verdict.ABSTAIN
    assert output.commitment_coverage == []


def test_present_text_evidence_requires_a_line() -> None:
    item = _coverage("AC-1", path="src/feature.py", line_start=None)

    output = _parse(_payload(item), [_commitment("AC-1")])

    assert output.verdict == Verdict.ABSTAIN


def test_rename_old_path_is_authoritative_deleted_metadata_not_present_text() -> None:
    changed_files = [
        DiffEvidenceFile(
            status="R",
            path="src/new.py",
            old_path="src/old.py",
            kind="text",
            source="tracked",
        )
    ]
    payload = _payload(_coverage("AC-1", path="src/old.py", line_start=None))

    output = parse_diff_reviewer_output(
        "local",
        1,
        f"<json>{json.dumps(payload)}</json>",
        elapsed_seconds=0.1,
        retries=0,
        commitments=[_commitment("AC-1")],
        changed_files=changed_files,
    )

    assert output.verdict == Verdict.APPROVE
    assert output.commitment_coverage[0].path == "src/old.py"


def test_recreated_rename_old_path_uses_present_text_line_rules() -> None:
    changed_files = [
        DiffEvidenceFile(
            status="R",
            path="src/new.py",
            old_path="src/old.py",
            kind="text",
            source="tracked",
        ),
        DiffEvidenceFile(
            status="A",
            path="src/old.py",
            old_path=None,
            kind="text",
            source="tracked",
        ),
    ]

    without_line = parse_diff_reviewer_output(
        "local",
        1,
        f"<json>{json.dumps(_payload(_coverage('AC-1', path='src/old.py', line_start=None)))}</json>",
        elapsed_seconds=0.1,
        retries=0,
        commitments=[_commitment("AC-1")],
        changed_files=changed_files,
    )
    with_line = parse_diff_reviewer_output(
        "local",
        1,
        f"<json>{json.dumps(_payload(_coverage('AC-1', path='src/old.py', line_start=7)))}</json>",
        elapsed_seconds=0.1,
        retries=0,
        commitments=[_commitment("AC-1")],
        changed_files=changed_files,
    )

    assert without_line.verdict == Verdict.ABSTAIN
    assert with_line.verdict == Verdict.APPROVE
    assert with_line.commitment_coverage[0].line_start == 7


@pytest.mark.parametrize(
    "ids",
    [
        ["AC-1"],
        ["AC-1", "AC-1", "TEST-1"],
        ["AC-1", "UNKNOWN", "TEST-1"],
    ],
)
def test_unknown_duplicate_or_missing_commitment_ids_abstain(ids: list[str]) -> None:
    commitments = [_commitment("AC-1"), _commitment("TEST-1")]
    payload = _payload(*(_coverage(commitment_id) for commitment_id in ids))

    output = _parse(payload, commitments)

    assert output.verdict == Verdict.ABSTAIN
    assert output.commitment_coverage == []


@pytest.mark.parametrize("commitment_id", ["ac-1", " AC-1", "AC-1 ", "AC-0", "AC-01", "X-1"])
def test_expected_commitment_ids_reject_noncanonical_values(commitment_id: str) -> None:
    with pytest.raises(ValueError, match="canonical"):
        expected_commitment_ids([_commitment(commitment_id)])


def test_expected_commitment_ids_reject_empty_and_duplicate_lists() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        expected_commitment_ids([])
    with pytest.raises(ValueError, match="unique"):
        expected_commitment_ids([_commitment("AC-1"), _commitment("AC-1")])


def test_scope_findings_are_strict_and_require_path_for_line() -> None:
    with pytest.raises(ValidationError):
        ScopeFinding(
            category=ScopeCategory.DEPENDENCY,
            risk="high",
            claim="A production dependency was added.",
            evidence="pyproject.toml:24",
            path=None,
            line_start=24,
        )


@pytest.mark.parametrize(
    "category",
    [
        "authentication",
        "authorization",
        "payments",
        "credential-handling",
        "destructive-data-operation",
        "schema-migration",
        "production-dependency",
        "deployment-configuration",
    ],
)
def test_high_risk_scope_categories_require_high_risk(category: str) -> None:
    with pytest.raises(ValidationError, match="risk=high"):
        ScopeFinding(
            category=category,
            risk="medium",
            claim="High-risk unplanned scope.",
            evidence=None,
            path=None,
            line_start=None,
        )


def test_scope_category_rejects_unbounded_values() -> None:
    with pytest.raises(ValidationError):
        ScopeFinding(
            category="whatever-the-model-invented",
            risk="low",
            claim="Unbounded category.",
            evidence=None,
            path=None,
            line_start=None,
        )


@pytest.mark.parametrize(
    "payload",
    [
        _payload(_coverage("AC-1", status="PARTIAL")),
        {
            **_payload(_coverage("AC-1")),
            "scope_findings": [
                {
                    "category": "dependency",
                    "risk": "medium",
                    "claim": "Unplanned dependency.",
                    "evidence": None,
                    "path": None,
                    "line_start": None,
                }
            ],
        },
        {
            **_payload(_coverage("AC-1")),
            "blocking_issues": [
                {
                    "id": "B1",
                    "section": "Tests",
                    "claim": "A blocker remains.",
                    "evidence": "Missing test.",
                }
            ],
        },
    ],
)
def test_approve_requires_complete_clean_coverage(payload: dict[str, object]) -> None:
    output = _parse(payload, [_commitment("AC-1")])

    assert output.verdict == Verdict.ABSTAIN


def test_abstain_requires_zero_confidence_empty_findings_and_runtime_diagnostic() -> None:
    base = {
        "reviewer": "local",
        "round": 1,
        "verdict": "ABSTAIN",
        "confidence": 0.0,
        "commitment_coverage": [],
        "scope_findings": [],
        "blocking_issues": [
            ReviewIssue(
                id="B0",
                section="runtime",
                claim="reviewer abstained: transport failed",
                evidence="timeout",
            )
        ],
        "suggestions": [],
        "per_clause": {key: "UNCLEAR" for key in DIFF_CLAUSES},
        "raw_response": "",
        "elapsed_seconds": 0.1,
    }

    DiffReviewerOutput.model_validate(base)
    for update in (
        {"confidence": 0.1},
        {"commitment_coverage": [_coverage("AC-1")]},
        {"scope_findings": [{"category": "other", "risk": "low", "claim": "x", "evidence": None, "path": None, "line_start": None}]},
        {"suggestions": [{"id": "S1", "section": "runtime", "claim": "x", "rationale": "x"}]},
        {"blocking_issues": []},
    ):
        with pytest.raises(ValidationError):
            DiffReviewerOutput.model_validate({**base, **update})


def test_diff_fallback_is_semantically_valid_abstain() -> None:
    output = diff_fallback_output(
        "local",
        1,
        [_commitment("AC-1")],
        claim="reviewer output unparseable",
    )

    assert output.verdict == Verdict.ABSTAIN
    assert output.confidence == 0
    assert output.commitment_coverage == []
    assert output.scope_findings == []
    assert output.suggestions == []
    assert output.blocking_issues[0].section == "runtime"


def test_diff_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DiffReviewerOutput(
            reviewer="local",
            round=1,
            verdict="APPROVE",
            confidence=0.8,
            commitment_coverage=[],
            scope_findings=[],
            blocking_issues=[],
            suggestions=[],
            per_clause=DIFF_CLAUSES,
            raw_response="{}",
            elapsed_seconds=0.1,
            unexpected=True,
        )


def test_diff_result_matches_public_schema_without_aggregate_confidence() -> None:
    digest = "a" * 64
    sha = "b" * 40
    result = DiffResult(
        schema_version="krystal-quorum.diff.v1",
        review_kind="diff",
        verdict="APPROVE",
        plan_provenance=PlanProvenance.VERIFIED_RECEIPT,
        plan=PlanManifest(path="docs/plans/change.md", sha256=digest, approval_sha256=digest),
        git=GitManifest(
            base_ref="HEAD",
            base_sha=sha,
            head_ref=None,
            head_sha=sha,
            merge_base_sha=None,
            working_tree=True,
        ),
        diff=DiffManifest(
            sha256=digest,
            changed_files=[DiffChangedFile(status="M", path="src/feature.py", old_path=None)],
        ),
        review_input_sha256=digest,
        quorum=QuorumMetrics(
            health="healthy",
            usable_reviewers=2,
            total_reviewers=2,
            distinct_families=2,
            agreement_ratio=1.0,
            contradiction_count=0,
        ),
        reviewers_used=["local-a", "local-b"],
        coverage=[
            AggregatedCoverageItem(
                commitment_id="AC-1",
                status="IMPLEMENTED",
                corroborated=True,
                reviewers=["local-a", "local-b"],
                evidence=["src/feature.py:12"],
            )
        ],
        scope_findings=[],
        unresolved_for_human=[],
        output_dir=".krystal-quorum/reviews/change_123",
    )

    payload = result.model_dump(mode="json")
    assert "confidence" not in payload
    with pytest.raises(ValidationError):
        DiffResult.model_validate({**payload, "confidence": 0.9})
