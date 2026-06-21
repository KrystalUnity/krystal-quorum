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
