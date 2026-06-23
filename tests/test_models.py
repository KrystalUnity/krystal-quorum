import pytest
from pydantic import ValidationError

from krystal_quorum.models import (
    ClauseStatus,
    IssueCluster,
    IssueClusterEdge,
    IssueClusterMember,
    ReconciledVerdict,
    ReviewIssue,
    ReviewerOutput,
    Verdict,
)


def test_reviewer_output_accepts_valid_payload():
    output = ReviewerOutput(
        reviewer="mock",
        round=1,
        verdict=Verdict.REVISE,
        confidence=0.75,
        blocking_issues=[],
        suggestions=[],
        per_clause={"acceptance.1": ClauseStatus.UNSATISFIED},
        raw_response="{}",
        elapsed_seconds=0.1,
    )

    assert output.verdict == Verdict.REVISE


def test_reviewer_output_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ReviewerOutput(
            reviewer="mock",
            round=1,
            verdict="APPROVE",
            confidence=0.5,
            blocking_issues=[],
            suggestions=[],
            per_clause={},
            raw_response="{}",
            elapsed_seconds=0.1,
            unexpected=True,
        )


def test_issue_cluster_accepts_edge_payload():
    issue = ReviewIssue(
        id="B1",
        section="Rollback",
        claim="No rollback plan is described.",
        evidence="Rollback is not mentioned.",
    )

    cluster = IssueCluster(
        topic="rollback",
        shared=True,
        reviewers=["agy", "claude"],
        representative=issue,
        members=[
            IssueClusterMember(
                reviewer="agy",
                issue_id="B1",
                section="Rollback",
                claim="No rollback plan is described.",
            ),
            IssueClusterMember(
                reviewer="claude",
                issue_id="B2",
                section="Rollback",
                claim="Missing backout path if deployment fails.",
            ),
        ],
        edges=[
            IssueClusterEdge(
                left_reviewer="agy",
                left_issue_id="B1",
                right_reviewer="claude",
                right_issue_id="B2",
                match_reason="shared topic rollback with absence intent; gap overlap: recovery",
            )
        ],
        match_reason="shared topic rollback with absence intent; gap overlap: recovery",
    )

    assert cluster.shared is True
    assert cluster.edges[0].right_issue_id == "B2"


def test_reconciled_verdict_defaults_issue_clusters_for_old_payload():
    payload = {
        "schema_version": "1.1",
        "plan_path": "plan.md",
        "plan_sha256": "abc",
        "timestamp": "2026-06-23T00:00:00+00:00",
        "reviewers_used": ["mock"],
        "diversity": {"status": "ok", "reviewers": []},
        "abstained_reviewers": [],
        "merged_verdict": "APPROVE",
        "confidence": 0.8,
        "shared_blocking_issues": [],
        "singleton_blocking_issues": [],
        "contradictions": [],
        "unresolved_for_human": [],
        "round1_outputs": [],
        "round2_outputs": [],
        "round2_delta": None,
        "round2_comparisons": [],
    }

    result = ReconciledVerdict.model_validate(payload)

    assert result.issue_clusters == []
