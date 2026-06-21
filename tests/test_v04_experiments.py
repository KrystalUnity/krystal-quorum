from experiments.v04_candidates import (
    ConfidenceSignals,
    candidate_confidence,
    candidate_issue_clusters,
    evaluate_rubric,
    try_repair_parse,
)
from krystal_quorum.models import ClauseStatus, ReviewIssue, ReviewerOutput, Verdict


def _valid_raw(verdict: str = "REVISE") -> str:
    return f"""
    <json>
    {{
      "verdict": "{verdict}",
      "confidence": 0.82,
      "blocking_issues": [
        {{
          "id": "B1",
          "section": "Rollback",
          "claim": "The plan has no rollback path.",
          "evidence": "Rollback is not mentioned."
        }}
      ],
      "suggestions": [],
      "per_clause": {{"rollback.plan": "UNSATISFIED"}}
    }}
    </json>
    """


def _output(reviewer: str, claim: str, section: str = "Release") -> ReviewerOutput:
    return ReviewerOutput(
        reviewer=reviewer,
        round=1,
        verdict=Verdict.REVISE,
        confidence=0.8,
        blocking_issues=[
            ReviewIssue(
                id=f"{reviewer}-B1",
                section=section,
                claim=claim,
                evidence="review evidence",
            )
        ],
        suggestions=[],
        per_clause={"rollback.plan": ClauseStatus.UNSATISFIED},
        raw_response="{}",
        elapsed_seconds=0.1,
    )


def test_retry_probe_recovers_from_malformed_first_attempt():
    probe = try_repair_parse(
        "ollama:gemma",
        round_number=1,
        raw_attempts=["not json", _valid_raw()],
    )

    assert probe.recovered is True
    assert probe.attempts_used == 2
    assert probe.failed_attempts == ("not json",)
    assert probe.output.verdict == Verdict.REVISE
    assert probe.output.retries == 1


def test_retry_probe_returns_abstain_when_all_attempts_are_malformed():
    probe = try_repair_parse(
        "ollama:gemma",
        round_number=1,
        raw_attempts=["not json", "still not json"],
    )

    assert probe.recovered is False
    assert probe.attempts_used == 2
    assert probe.output.verdict == Verdict.ABSTAIN
    assert probe.output.retries == 1
    assert probe.failed_attempts == ("not json", "still not json")


def test_candidate_consensus_groups_rollback_synonyms():
    clusters = candidate_issue_clusters(
        [
            _output("codex", "No rollback plan is described."),
            _output("agy", "Missing backout path if deployment fails."),
        ]
    )

    shared = [cluster for cluster in clusters if cluster.shared]

    assert len(shared) == 1
    assert shared[0].reviewers == ("agy", "codex")
    assert shared[0].topic == "rollback"


def test_candidate_consensus_keeps_unrelated_issues_separate():
    clusters = candidate_issue_clusters(
        [
            _output("codex", "No rollback plan is described."),
            _output("grok", "The pytest verification command is missing.", section="Tests"),
        ]
    )

    assert all(not cluster.shared for cluster in clusters)
    assert {cluster.topic for cluster in clusters} == {"rollback", "tests"}


def test_candidate_confidence_penalizes_weak_review_signals():
    strong = candidate_confidence(
        ConfidenceSignals(
            total_reviewers=4,
            non_abstained=4,
            diversity_status="ok",
            shared_blockers=1,
            singleton_blockers=0,
            contradictions=0,
            round2_delta=0,
        )
    )
    abstained = candidate_confidence(
        ConfidenceSignals(
            total_reviewers=4,
            non_abstained=2,
            diversity_status="ok",
            shared_blockers=1,
            singleton_blockers=0,
            contradictions=0,
            round2_delta=0,
        )
    )
    low_diversity = candidate_confidence(
        ConfidenceSignals(
            total_reviewers=4,
            non_abstained=4,
            diversity_status="low",
            shared_blockers=1,
            singleton_blockers=0,
            contradictions=0,
            round2_delta=0,
        )
    )
    contradictory = candidate_confidence(
        ConfidenceSignals(
            total_reviewers=4,
            non_abstained=4,
            diversity_status="ok",
            shared_blockers=1,
            singleton_blockers=0,
            contradictions=1,
            round2_delta=0,
        )
    )
    singleton_only = candidate_confidence(
        ConfidenceSignals(
            total_reviewers=4,
            non_abstained=4,
            diversity_status="ok",
            shared_blockers=0,
            singleton_blockers=2,
            contradictions=0,
            round2_delta=0,
        )
    )

    assert strong > abstained
    assert strong > low_diversity
    assert strong > contradictory
    assert strong > singleton_only


def test_rubric_flags_missing_preflight_sections():
    findings = {finding.key: finding for finding in evaluate_rubric("Make the button look nice.")}

    assert findings["acceptance.criteria"].status == ClauseStatus.UNSATISFIED
    assert findings["rollback.plan"].status == ClauseStatus.UNSATISFIED
    assert findings["tests.verification"].status == ClauseStatus.UNSATISFIED
    assert findings["security.risk"].status == ClauseStatus.UNCLEAR


def test_rubric_accepts_structured_plan():
    plan = """
    ## Acceptance Criteria
    - Done when export returns CSV and invalid filters show an error.

    ## Rollback Plan
    - Revert the feature flag and redeploy the previous worker.

    ## Tests and Verification
    - Run pytest tests/test_exports.py and verify the CLI smoke test.

    ## Security
    - No secrets are logged; permission checks reuse the existing role gate.

    ## Dependencies
    - No new packages; use the existing CSV writer.

    ## Observability
    - Log export failures and monitor the existing export_error_total metric.
    """

    findings = {finding.key: finding for finding in evaluate_rubric(plan)}

    assert all(finding.status == ClauseStatus.SATISFIED for finding in findings.values())
