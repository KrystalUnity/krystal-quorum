from krystal_quorum.issue_matching import cluster_issues
from krystal_quorum.models import ReviewIssue


def issue(
    id: str,
    claim: str,
    section: str = "Plan",
    evidence: str = "evidence",
) -> ReviewIssue:
    return ReviewIssue(id=id, section=section, claim=claim, evidence=evidence)


def shared(clusters):
    return [cluster for cluster in clusters if cluster.shared]


def test_groups_rollback_and_backout_by_shared_gap_term():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "No rollback plan is described.")),
            ("claude", issue("B2", "Missing backout path if deployment fails.")),
        ]
    )

    assert len(shared(clusters)) == 1
    assert shared(clusters)[0].topic == "rollback"
    assert shared(clusters)[0].match_reason == (
        "shared topic rollback with absence intent; gap overlap: recovery"
    )


def test_absence_intent_requires_shared_gap_terms():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "No security audit is scheduled.")),
            ("claude", issue("B2", "Missing security logging for exports.")),
        ]
    )

    assert shared(clusters) == []
    assert {cluster.representative.id for cluster in clusters} == {"B1", "B2"}


def test_plan_section_token_does_not_create_support_overlap_consensus():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "Security audit schedule is absent.")),
            ("claude", issue("B2", "Security export logging is undefined.")),
        ]
    )

    assert shared(clusters) == []


def test_connected_component_joins_by_non_representative_match():
    clusters = cluster_issues(
        [
            ("a", issue("B1", "No rollback plan is described.")),
            ("b", issue("B2", "Missing backout path if deployment fails.")),
            ("c", issue("B3", "Deployment failure handling is absent.")),
        ]
    )

    cluster = shared(clusters)[0]

    assert cluster.reviewers == ["a", "b", "c"]
    assert {member.issue_id for member in cluster.members} == {"B1", "B2", "B3"}
    assert len(cluster.edges) == 2
    assert any(edge.left_issue_id == "B2" and edge.right_issue_id == "B3" for edge in cluster.edges)


def test_same_reviewer_duplicates_do_not_create_shared_cluster():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "No rollback plan is described.")),
            ("agy", issue("B2", "Missing backout path if deployment fails.")),
        ]
    )

    assert shared(clusters) == []


def test_general_fallback_does_not_match_without_exact_fingerprint():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "The story is vague.")),
            ("claude", issue("B2", "The description is ambiguous.")),
        ]
    )

    assert [cluster.topic for cluster in clusters] == ["general", "general"]
    assert shared(clusters) == []


def test_exact_fingerprint_can_match_general_findings():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "The story is vague.")),
            ("claude", issue("B2", "The story is vague.")),
        ]
    )

    assert len(shared(clusters)) == 1
    assert clusters[0].topic == "general"
    assert clusters[0].match_reason == "exact fingerprint match"


def test_supporting_overlap_threshold_groups_richer_findings():
    clusters = cluster_issues(
        [
            ("glm", issue("B1", "Security permission checks for admin export need detail.")),
            ("claude", issue("B2", "Auth permission checks for admin export need coverage.")),
        ]
    )

    cluster = shared(clusters)[0]

    assert cluster.topic == "security"
    assert "overlap coefficient" in cluster.match_reason
    assert "supporting overlap" in cluster.match_reason


def test_ambiguous_tied_topic_becomes_general():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "Rollback auth is missing.")),
            ("claude", issue("B2", "Auth rollback is missing.")),
        ]
    )

    assert clusters[0].topic == "general"
