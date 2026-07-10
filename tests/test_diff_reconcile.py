from __future__ import annotations

from collections.abc import Iterable, Sequence

import pytest

from krystal_quorum.commitments import Commitment, CommitmentCategory
from krystal_quorum.diff_models import (
    DIFF_CLAUSE_IDS,
    HIGH_RISK_SCOPE_CATEGORIES,
    CoverageStatus,
    DiffChangedFile,
    DiffReviewerOutput,
    PlanProvenance,
    QuorumHealth,
    ScopeCategory,
    ScopeFinding,
    ScopeRisk,
)
from krystal_quorum.diff_reconcile import (
    MAX_EVIDENCE_ITEMS,
    MAX_EVIDENCE_LENGTH,
    reconcile_diff,
)
from krystal_quorum.models import ClauseStatus, ReviewIssue, Verdict
from krystal_quorum.reviewer_specs import DataBoundary, ReviewerSpec


DIGEST = "a" * 64
GIT_SHA = "b" * 40


def _commitments(*ids: str) -> list[Commitment]:
    return [
        Commitment(
            id=commitment_id,
            category=CommitmentCategory.ACCEPTANCE,
            text=f"Implement {commitment_id}.",
            source_line=index,
            group=None,
        )
        for index, commitment_id in enumerate(ids, start=1)
    ]


def _spec(reviewer_id: str, *, family: str | None = None) -> ReviewerSpec:
    return ReviewerSpec(
        reviewer_id=reviewer_id,
        backend="command",
        family=family or reviewer_id,
        endpoint=None,
        data_boundary=DataBoundary.LOCAL,
    )


def _output(
    reviewer: str,
    statuses: Sequence[tuple[str, CoverageStatus]],
    *,
    round_number: int = 1,
    scope_findings: Iterable[ScopeFinding] = (),
    blocking_issues: Iterable[ReviewIssue] = (),
    evidence: str | None = None,
    abstain: bool = False,
) -> DiffReviewerOutput:
    scope = list(scope_findings)
    blockers = list(blocking_issues)
    if abstain:
        return DiffReviewerOutput(
            reviewer=reviewer,
            round=round_number,
            verdict=Verdict.ABSTAIN,
            confidence=0.0,
            commitment_coverage=[],
            scope_findings=[],
            blocking_issues=[
                ReviewIssue(
                    id="RUNTIME-1",
                    section="runtime",
                    claim="Reviewer abstained because evidence was unavailable.",
                    evidence="timeout",
                )
            ],
            suggestions=[],
            per_clause={key: ClauseStatus.UNCLEAR for key in DIFF_CLAUSE_IDS},
            raw_response="",
            elapsed_seconds=0.1,
        )

    clean = all(status == CoverageStatus.IMPLEMENTED for _, status in statuses)
    verdict = Verdict.APPROVE if clean and not scope and not blockers else Verdict.REVISE
    return DiffReviewerOutput(
        reviewer=reviewer,
        round=round_number,
        verdict=verdict,
        confidence=0.8,
        commitment_coverage=[
            {
                "commitment_id": commitment_id,
                "status": status,
                "claim": f"{commitment_id} is {status.value}.",
                "evidence": evidence,
                "path": "src/feature.py" if status == CoverageStatus.IMPLEMENTED else None,
                "line_start": 1 if status == CoverageStatus.IMPLEMENTED else None,
            }
            for commitment_id, status in statuses
        ],
        scope_findings=scope,
        blocking_issues=blockers,
        suggestions=[],
        per_clause={key: ClauseStatus.SATISFIED for key in DIFF_CLAUSE_IDS},
        raw_response="{}",
        elapsed_seconds=0.1,
    )


def _scope(
    category: ScopeCategory,
    claim: str,
    *,
    path: str | None = "src/feature.py",
) -> ScopeFinding:
    return ScopeFinding(
        category=category,
        risk=ScopeRisk.HIGH if category in HIGH_RISK_SCOPE_CATEGORIES else ScopeRisk.MEDIUM,
        claim=claim,
        evidence="Changed code demonstrates the unplanned scope.",
        path=path,
        line_start=2 if path else None,
    )


def _reconcile(
    commitments: Sequence[Commitment],
    outputs: Sequence[DiffReviewerOutput],
    specs: Sequence[ReviewerSpec],
):
    return reconcile_diff(
        commitments=commitments,
        round1_outputs=[output for output in outputs if output.round == 1],
        round2_outputs=[output for output in outputs if output.round == 2],
        reviewer_specs=specs,
        plan_provenance=PlanProvenance.VERIFIED_RECEIPT,
        plan_path="docs/plans/change.md",
        plan_sha256=DIGEST,
        approval_sha256="c" * 64,
        base_ref="main",
        base_sha=GIT_SHA,
        head_ref=None,
        head_sha="d" * 40,
        merge_base_sha=None,
        working_tree=True,
        diff_sha256="e" * 64,
        changed_files=[DiffChangedFile(status="M", path="src/feature.py")],
        review_input_sha256="f" * 64,
        output_dir=".krystal-quorum/reviews/change_123",
    )


def test_corroborated_missing_blocks_in_stable_commitment_order() -> None:
    commitments = _commitments("AC-2", "AC-1")
    statuses = [
        ("AC-2", CoverageStatus.IMPLEMENTED),
        ("AC-1", CoverageStatus.MISSING),
    ]

    result = _reconcile(
        commitments,
        [_output("reviewer-b", statuses), _output("reviewer-a", statuses)],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.BLOCK
    assert [item.commitment_id for item in result.coverage] == ["AC-2", "AC-1"]
    assert result.coverage[1].status == CoverageStatus.MISSING
    assert result.coverage[1].corroborated is True
    assert result.coverage[1].reviewers == ["reviewer-a", "reviewer-b"]
    assert result.coverage[1].evidence == []


@pytest.mark.parametrize("category", sorted(HIGH_RISK_SCOPE_CATEGORIES, key=str))
def test_corroborated_high_risk_scope_blocks(category: ScopeCategory) -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    claim = "Unplanned privileged production behavior is introduced."

    result = _reconcile(
        _commitments("AC-1"),
        [
            _output("reviewer-a", statuses, scope_findings=[_scope(category, claim)]),
            _output("reviewer-b", statuses, scope_findings=[_scope(category, claim)]),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.BLOCK
    assert len(result.scope_findings) == 1
    assert any("Corroborated high-risk scope" in item for item in result.unresolved_for_human)


@pytest.mark.parametrize("status", [CoverageStatus.PARTIAL, CoverageStatus.NOT_EVIDENT])
def test_corroborated_incomplete_coverage_revises(status: CoverageStatus) -> None:
    statuses = [("AC-1", status)]

    result = _reconcile(
        _commitments("AC-1"),
        [_output("reviewer-a", statuses), _output("reviewer-b", statuses)],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.REVISE
    assert result.coverage[0].status == status
    assert result.coverage[0].corroborated is True


def test_duplicate_reviewer_missing_is_one_vote_and_cannot_block() -> None:
    statuses = [("AC-1", CoverageStatus.MISSING)]

    result = _reconcile(
        _commitments("AC-1"),
        [_output("reviewer-a", statuses), _output("reviewer-a", statuses)],
        [_spec("reviewer-a"), _spec("reviewer-a")],
    )

    assert result.verdict == Verdict.REVISE
    assert result.quorum.usable_reviewers == 1
    assert result.quorum.total_reviewers == 1
    assert result.quorum.health == QuorumHealth.DEGRADED
    assert result.coverage[0].reviewers == ["reviewer-a"]
    assert result.coverage[0].corroborated is False
    assert any(
        "Singleton MISSING commitment AC-1" in item for item in result.unresolved_for_human
    )


def test_singleton_free_text_blocker_revises_for_human_triage() -> None:
    blocker = ReviewIssue(
        id="B1",
        section="security",
        claim="A runtime guard is absent.",
        evidence="No guard appears in the changed code.",
    )
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]

    result = _reconcile(
        _commitments("AC-1"),
        [_output("reviewer-a", statuses, blocking_issues=[blocker])],
        [_spec("reviewer-a")],
    )

    assert result.verdict == Verdict.REVISE
    assert any("Singleton blocker" in item for item in result.unresolved_for_human)


def test_contradictory_commitment_statuses_revise_and_require_human_triage() -> None:
    result = _reconcile(
        _commitments("AC-1"),
        [
            _output("reviewer-a", [("AC-1", CoverageStatus.IMPLEMENTED)]),
            _output("reviewer-b", [("AC-1", CoverageStatus.MISSING)]),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.REVISE
    assert result.quorum.contradiction_count == 1
    assert result.quorum.agreement_ratio == 0.0
    assert any("Contradiction on AC-1" in item for item in result.unresolved_for_human)


def test_agreement_ratio_counts_only_commitments_with_a_unique_modal_status() -> None:
    commitments = _commitments("AC-1", "AC-2")
    result = _reconcile(
        commitments,
        [
            _output(
                "reviewer-a",
                [
                    ("AC-1", CoverageStatus.IMPLEMENTED),
                    ("AC-2", CoverageStatus.IMPLEMENTED),
                ],
            ),
            _output(
                "reviewer-b",
                [
                    ("AC-1", CoverageStatus.IMPLEMENTED),
                    ("AC-2", CoverageStatus.MISSING),
                ],
            ),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.quorum.agreement_ratio == 0.5
    assert result.quorum.contradiction_count == 1


def test_all_abstain_collapses_to_revise_with_diagnostics() -> None:
    result = _reconcile(
        _commitments("AC-1"),
        [
            _output("reviewer-a", [], abstain=True),
            _output("reviewer-b", [], abstain=True),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.REVISE
    assert result.quorum.health == QuorumHealth.COLLAPSED
    assert result.quorum.usable_reviewers == 0
    assert result.quorum.agreement_ratio == 0.0
    assert any("All reviewers abstained" in item for item in result.unresolved_for_human)


def test_partial_abstention_and_single_usable_reviewer_are_degraded() -> None:
    result = _reconcile(
        _commitments("AC-1"),
        [
            _output("reviewer-a", [("AC-1", CoverageStatus.IMPLEMENTED)]),
            _output("reviewer-b", [], abstain=True),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.quorum.health == QuorumHealth.DEGRADED
    assert result.quorum.usable_reviewers == 1
    assert any("Partial quorum" in item for item in result.unresolved_for_human)


def test_all_required_commitments_implemented_approves_with_explicit_metadata() -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    result = _reconcile(
        _commitments("AC-1"),
        [_output("reviewer-a", statuses), _output("reviewer-b", statuses)],
        [_spec("reviewer-a", family="same"), _spec("reviewer-b", family="same")],
    )

    assert result.verdict == Verdict.APPROVE
    assert result.quorum.health == QuorumHealth.HEALTHY
    assert result.quorum.distinct_families == 1
    assert result.plan.path == "docs/plans/change.md"
    assert result.plan.sha256 == DIGEST
    assert result.plan.approval_sha256 == "c" * 64
    assert result.git.base_ref == "main"
    assert result.git.base_sha == GIT_SHA
    assert result.git.head_sha == "d" * 40
    assert result.diff.sha256 == "e" * 64
    assert result.review_input_sha256 == "f" * 64
    assert result.output_dir == ".krystal-quorum/reviews/change_123"
    assert "confidence" not in result.model_dump(mode="json")


def test_na_for_required_commitment_revises() -> None:
    statuses = [("AC-1", CoverageStatus.NA)]

    result = _reconcile(
        _commitments("AC-1"),
        [_output("reviewer-a", statuses), _output("reviewer-b", statuses)],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.REVISE
    assert result.coverage[0].status == CoverageStatus.NA
    assert any("required commitment AC-1" in item for item in result.unresolved_for_human)


def test_no_commitments_is_an_error() -> None:
    with pytest.raises(ValueError, match="commitment IDs must not be empty"):
        _reconcile([], [], [_spec("reviewer-a")])


def test_round_two_is_effective_per_reviewer_without_dropping_round_one_peers() -> None:
    missing = [("AC-1", CoverageStatus.MISSING)]
    implemented = [("AC-1", CoverageStatus.IMPLEMENTED)]
    result = _reconcile(
        _commitments("AC-1"),
        [
            _output("reviewer-a", missing),
            _output("reviewer-b", implemented),
            _output("reviewer-a", implemented, round_number=2),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.APPROVE
    assert result.quorum.usable_reviewers == 2
    assert result.coverage[0].reviewers == ["reviewer-a", "reviewer-b"]


def test_scope_corroboration_does_not_merge_different_non_null_paths() -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    claim = "Unplanned credential logging is introduced."
    category = ScopeCategory.CREDENTIAL_HANDLING

    result = _reconcile(
        _commitments("AC-1"),
        [
            _output(
                "reviewer-a",
                statuses,
                scope_findings=[_scope(category, claim, path="src/feature.py")],
            ),
            _output(
                "reviewer-b",
                statuses,
                scope_findings=[_scope(category, claim, path="src/other.py")],
            ),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.REVISE
    assert len(result.scope_findings) == 2
    assert not any("Corroborated high-risk scope" in item for item in result.unresolved_for_human)


def test_specific_scope_category_and_path_corroborate_semantic_paraphrases() -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    category = ScopeCategory.CREDENTIAL_HANDLING

    result = _reconcile(
        _commitments("AC-1"),
        [
            _output(
                "reviewer-a",
                statuses,
                scope_findings=[
                    _scope(category, "Credentials are written into logs.", path="src/auth.py")
                ],
            ),
            _output(
                "reviewer-b",
                statuses,
                scope_findings=[
                    _scope(
                        category,
                        "Diagnostic output exposes secret values.",
                        path="src/auth.py",
                    )
                ],
            ),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.BLOCK
    assert len(result.scope_findings) == 1
    assert result.quorum.contradiction_count == 0
    assert any("Corroborated high-risk scope" in item for item in result.unresolved_for_human)


def test_null_path_scope_paraphrases_require_shared_semantic_anchors() -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    category = ScopeCategory.CREDENTIAL_HANDLING

    result = _reconcile(
        _commitments("AC-1"),
        [
            _output(
                "reviewer-a",
                statuses,
                scope_findings=[
                    _scope(category, "Credentials are written into logs.", path=None)
                ],
            ),
            _output(
                "reviewer-b",
                statuses,
                scope_findings=[
                    _scope(category, "Diagnostic output exposes secret values.", path=None)
                ],
            ),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.BLOCK
    assert len(result.scope_findings) == 1


@pytest.mark.parametrize(
    "opposite_claim",
    [
        "The authentication check is removed.",
        "The authentication check is not added.",
        "The authentication check isn't added.",
        "No authentication check is added.",
    ],
)
def test_opposite_scope_operations_do_not_corroborate_and_signal_contradiction(
    opposite_claim: str,
) -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    category = ScopeCategory.AUTHENTICATION

    result = _reconcile(
        _commitments("AC-1"),
        [
            _output(
                "reviewer-a",
                statuses,
                scope_findings=[
                    _scope(category, "The authentication check is added.", path="src/auth.py")
                ],
            ),
            _output(
                "reviewer-b",
                statuses,
                scope_findings=[_scope(category, opposite_claim, path="src/auth.py")],
            ),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.REVISE
    assert len(result.scope_findings) == 2
    assert result.quorum.contradiction_count == 1
    assert any("Scope contradiction" in item for item in result.unresolved_for_human)
    assert not any("Corroborated high-risk scope" in item for item in result.unresolved_for_human)


def test_long_opposite_scope_operations_use_raw_claims_for_corroboration() -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    category = ScopeCategory.AUTHENTICATION
    prefix = "context " * 70
    added_claim = f"{prefix}The authentication check is added."
    removed_claim = f"{prefix}The authentication check is removed."

    assert len(added_claim) > MAX_EVIDENCE_LENGTH
    assert len(removed_claim) > MAX_EVIDENCE_LENGTH

    result = _reconcile(
        _commitments("AC-1"),
        [
            _output(
                "reviewer-a",
                statuses,
                scope_findings=[_scope(category, added_claim, path="src/auth.py")],
            ),
            _output(
                "reviewer-b",
                statuses,
                scope_findings=[_scope(category, removed_claim, path="src/auth.py")],
            ),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.REVISE
    assert len(result.scope_findings) == 2
    assert result.quorum.contradiction_count == 1
    assert all(len(finding.claim) <= MAX_EVIDENCE_LENGTH for finding in result.scope_findings)
    assert any("Scope contradiction" in item for item in result.unresolved_for_human)
    assert not any("Corroborated high-risk scope" in item for item in result.unresolved_for_human)


def test_generic_scope_category_does_not_merge_distinct_explicit_objects() -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    category = ScopeCategory.OTHER

    result = _reconcile(
        _commitments("AC-1"),
        [
            _output(
                "reviewer-a",
                statuses,
                scope_findings=[
                    _scope(category, "Adds feature behavior for cache.", path="src/service.py")
                ],
            ),
            _output(
                "reviewer-b",
                statuses,
                scope_findings=[
                    _scope(category, "Adds feature behavior for billing.", path="src/service.py")
                ],
            ),
        ],
        [_spec("reviewer-a"), _spec("reviewer-b")],
    )

    assert result.verdict == Verdict.REVISE
    assert len(result.scope_findings) == 2
    assert result.quorum.contradiction_count == 0


def test_scope_grouping_remains_complete_link_and_deterministic() -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    category = ScopeCategory.OTHER
    outputs = [
        _output(
            "reviewer-a",
            statuses,
            scope_findings=[
                _scope(category, "Credentials are written into logs.", path=None)
            ],
        ),
        _output(
            "reviewer-b",
            statuses,
            scope_findings=[
                _scope(
                    category,
                    "Authentication package logs credential tokens.",
                    path=None,
                )
            ],
        ),
        _output(
            "reviewer-c",
            statuses,
            scope_findings=[
                _scope(
                    category,
                    "Authentication dependency package policy changes.",
                    path=None,
                )
            ],
        ),
    ]
    specs = [_spec("reviewer-a"), _spec("reviewer-b"), _spec("reviewer-c")]

    first = _reconcile(_commitments("AC-1"), outputs, specs)
    second = _reconcile(_commitments("AC-1"), list(reversed(outputs)), specs)

    assert len(first.scope_findings) == 2
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_output_is_deterministic_when_reviewer_outputs_arrive_in_different_order() -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    outputs = [
        _output("reviewer-a", statuses, evidence="src/feature.py:1"),
        _output("reviewer-b", statuses, evidence="src/feature.py:2"),
    ]
    specs = [_spec("reviewer-a"), _spec("reviewer-b")]

    first = _reconcile(_commitments("AC-1"), outputs, specs)
    second = _reconcile(_commitments("AC-1"), list(reversed(outputs)), specs)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_coverage_evidence_count_and_strings_are_bounded() -> None:
    statuses = [("AC-1", CoverageStatus.IMPLEMENTED)]
    specs = [_spec(f"reviewer-{index}") for index in range(MAX_EVIDENCE_ITEMS + 2)]
    outputs = [
        _output(
            spec.reviewer_id,
            statuses,
            evidence=f"evidence-{index}-" + "x" * (MAX_EVIDENCE_LENGTH + 20),
        )
        for index, spec in enumerate(specs)
    ]

    result = _reconcile(_commitments("AC-1"), outputs, specs)

    assert len(result.coverage[0].evidence) == MAX_EVIDENCE_ITEMS
    assert all(len(item) <= MAX_EVIDENCE_LENGTH for item in result.coverage[0].evidence)
