from krystal_quorum.models import ClauseStatus, ReviewIssue, ReviewerOutput, Verdict
from krystal_quorum.reconcile import reconcile


def output(reviewer: str, verdict: Verdict, issue: ReviewIssue | None = None) -> ReviewerOutput:
    return ReviewerOutput(
        reviewer=reviewer,
        round=1,
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


def test_reconcile_rejects_consensus_blocker():
    issue = ReviewIssue(id="B1", section="Acceptance", claim="Missing exit codes", evidence="none")

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[output("a", Verdict.BLOCK, issue), output("b", Verdict.BLOCK, issue)],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.BLOCK
    assert len(result.consensus_blocking_issues) == 1


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


def test_reconcile_ignores_abstained_reviewer_confidence():
    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[
            output("a", Verdict.APPROVE),
            output("b", Verdict.ABSTAIN),
        ],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.APPROVE
    assert result.confidence == 0.8
    assert result.abstained_reviewers == ["b"]
