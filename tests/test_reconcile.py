from krystal_quorum.models import ClauseStatus, DiversityReport, ReviewIssue, ReviewerFamily, ReviewerOutput, Verdict
from krystal_quorum.reconcile import reconcile


def output(
    reviewer: str,
    verdict: Verdict,
    issue: ReviewIssue | None = None,
    *,
    round_number: int = 1,
) -> ReviewerOutput:
    return ReviewerOutput(
        reviewer=reviewer,
        round=round_number,  # type: ignore[arg-type]
        verdict=verdict,
        confidence=0.8,
        blocking_issues=[issue] if issue else [],
        suggestions=[],
        per_clause={
            "acceptance.1": ClauseStatus.UNSATISFIED if issue else ClauseStatus.SATISFIED
        },
        raw_response="{}",
        elapsed_seconds=0.1,
    )


def test_reconcile_rejects_shared_blocker():
    issue = ReviewIssue(id="B1", section="Acceptance", claim="Missing exit codes", evidence="none")

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[output("a", Verdict.BLOCK, issue), output("b", Verdict.BLOCK, issue)],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.BLOCK
    assert len(result.shared_blocking_issues) == 1


def test_reconcile_groups_paraphrased_shared_issues():
    issue_a = ReviewIssue(
        id="B1",
        section="Acceptance",
        claim="Missing explicit acceptance criteria for the export button",
        evidence="No acceptance section was found.",
    )
    issue_b = ReviewIssue(
        id="B2",
        section="Acceptance",
        claim="The export button plan lacks defined acceptance criteria",
        evidence="The plan says to make it look nice but gives no pass/fail checks.",
    )

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[output("a", Verdict.REVISE, issue_a), output("b", Verdict.REVISE, issue_b)],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.BLOCK
    assert len(result.shared_blocking_issues) == 1
    assert result.singleton_blocking_issues == []


def test_reconcile_promotes_rollback_backout_consensus():
    issue_a = ReviewIssue(
        id="B1",
        section="Plan",
        claim="No rollback plan is described.",
        evidence="",
    )
    issue_b = ReviewIssue(
        id="B2",
        section="Plan",
        claim="Missing backout path if deployment fails.",
        evidence="",
    )

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["agy", "claude"],
        round1_outputs=[
            output("agy", Verdict.REVISE, issue_a),
            output("claude", Verdict.REVISE, issue_b),
        ],
        round2_outputs=[],
    )

    assert result.schema_version == "1.2"
    assert result.merged_verdict == Verdict.BLOCK
    assert len(result.shared_blocking_issues) == 1
    assert result.singleton_blocking_issues == []
    assert result.issue_clusters[0].edges[0].match_reason == (
        "shared topic rollback with absence intent; gap overlap: recovery"
    )


def test_reconcile_legacy_matcher_env_rolls_back_consensus(monkeypatch):
    monkeypatch.setenv("KRYSTAL_QUORUM_CONSENSUS_MATCHER", "legacy")
    issue_a = ReviewIssue(
        id="B1",
        section="Plan",
        claim="No rollback plan is described.",
        evidence="",
    )
    issue_b = ReviewIssue(
        id="B2",
        section="Plan",
        claim="Missing backout path if deployment fails.",
        evidence="",
    )

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["agy", "claude"],
        round1_outputs=[
            output("agy", Verdict.REVISE, issue_a),
            output("claude", Verdict.REVISE, issue_b),
        ],
        round2_outputs=[],
    )

    assert result.schema_version == "1.2"
    assert result.shared_blocking_issues == []
    assert len(result.singleton_blocking_issues) == 2
    assert result.issue_clusters == []


def test_reconcile_revises_singleton_blocker():
    issue = ReviewIssue(id="B1", section="Acceptance", claim="Missing rollback", evidence="none")

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[output("a", Verdict.REVISE, issue), output("b", Verdict.APPROVE)],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.REVISE
    assert result.singleton_blocking_issues == [issue]


def test_reconcile_flags_collapsed_multi_reviewer_quorum():
    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b", "c"],
        round1_outputs=[
            output("a", Verdict.APPROVE),
            output("b", Verdict.ABSTAIN),
            output("c", Verdict.ABSTAIN),
        ],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.REVISE
    assert result.confidence < 0.3
    assert result.abstained_reviewers == ["b", "c"]
    assert result.unresolved_for_human == [
        "Quorum collapsed: only 1 of 3 reviewers produced usable output."
    ]


def test_reconcile_flags_partial_multi_reviewer_abstentions():
    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b", "c"],
        round1_outputs=[
            output("a", Verdict.APPROVE),
            output("b", Verdict.APPROVE),
            output("c", Verdict.ABSTAIN),
        ],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.APPROVE
    assert result.confidence < 0.8
    assert "Partial quorum: 1 of 3 reviewers abstained." in result.unresolved_for_human


def test_reconcile_penalizes_low_diversity_confidence():
    diversity = DiversityReport(
        status="low",
        reviewers=[
            ReviewerFamily(reviewer="a", backend="openai", family="gpt-4"),
            ReviewerFamily(reviewer="b", backend="openai", family="gpt-4"),
        ],
        reason="reviewers share model family gpt-4",
    )

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[output("a", Verdict.APPROVE), output("b", Verdict.APPROVE)],
        round2_outputs=[],
        diversity=diversity,
    )

    assert result.merged_verdict == Verdict.APPROVE
    assert result.confidence == 0.6


def test_reconcile_keeps_single_block_fail_safe_with_majority_approve():
    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b", "c"],
        round1_outputs=[
            output("a", Verdict.BLOCK),
            output("b", Verdict.APPROVE),
            output("c", Verdict.APPROVE),
        ],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.BLOCK


def test_reconcile_normalizes_per_clause_keys_for_contradictions():
    left = output("a", Verdict.APPROVE)
    left.per_clause = {"Acceptance.Criteria": ClauseStatus.SATISFIED}
    right = output("b", Verdict.REVISE)
    right.per_clause = {"acceptance_criteria": ClauseStatus.UNSATISFIED}

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[left, right],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.REVISE
    assert result.contradictions[0].clause_id == "acceptance.criteria"
    assert result.contradictions[0].severity == "high"


def test_reconcile_normalizes_extended_rubric_clause_keys():
    left = output("a", Verdict.APPROVE)
    left.per_clause = {"Security Risk": ClauseStatus.SATISFIED}
    right = output("b", Verdict.REVISE)
    right.per_clause = {"security_risk": ClauseStatus.UNCLEAR}

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[left, right],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.REVISE
    assert result.contradictions[0].clause_id == "security.risk"
    assert result.unresolved_for_human == [
        "Contradiction on security.risk: human triage required."
    ]


def test_reconcile_flags_unknown_per_clause_keys():
    left = output("a", Verdict.APPROVE)
    left.per_clause = {"deployment.window": ClauseStatus.SATISFIED}
    right = output("b", Verdict.APPROVE)

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[left, right],
        round2_outputs=[],
    )

    assert "Unknown per_clause key from a ignored: deployment.window" in result.unresolved_for_human


def test_reconcile_reports_round2_delta_for_comparable_verdict_changes():
    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b", "c"],
        round1_outputs=[
            output("a", Verdict.APPROVE),
            output("b", Verdict.ABSTAIN),
            output("c", Verdict.REVISE),
        ],
        round2_outputs=[
            output("a", Verdict.BLOCK, round_number=2),
            output("b", Verdict.APPROVE, round_number=2),
            output("c", Verdict.REVISE, round_number=2),
        ],
    )

    assert result.round2_delta == 1
    assert result.round2_comparisons[0].changed is True
    assert result.round2_comparisons[1].comparable is False
    assert result.round2_comparisons[1].changed is None
    assert result.round2_comparisons[2].changed is False


def test_reconcile_includes_schema_version():
    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a"],
        round1_outputs=[output("a", Verdict.APPROVE)],
        round2_outputs=[],
    )

    assert result.schema_version == "1.2"
