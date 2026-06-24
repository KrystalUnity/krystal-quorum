from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
import os
import re

from krystal_quorum.diversity import analyze_reviewer_diversity
from krystal_quorum.issue_matching import cluster_issues, legacy_group_issues
from krystal_quorum.models import (
    ClauseStatus,
    ContradictionFinding,
    DiversityReport,
    IssueCluster,
    ReconciledVerdict,
    Round2Comparison,
    ReviewerOutput,
    Verdict,
)
from krystal_quorum.persist import plan_sha256

SCHEMA_VERSION = "1.2"
COMPARABLE_ROUND2_VERDICTS = {Verdict.APPROVE, Verdict.REVISE, Verdict.BLOCK}
CLAUSE_KEY_ALIASES = {
    "acceptance.criteria": "acceptance.criteria",
    "acceptance": "acceptance.criteria",
    "rollback.plan": "rollback.plan",
    "rollback": "rollback.plan",
    "tests.verification": "tests.verification",
    "test.verification": "tests.verification",
    "verification": "tests.verification",
    "safety.assumptions": "safety.assumptions",
    "safety": "safety.assumptions",
    "security.risk": "security.risk",
    "security": "security.risk",
    "risk": "security.risk",
    "dependencies.scope": "dependencies.scope",
    "dependency.scope": "dependencies.scope",
    "dependencies": "dependencies.scope",
    "dependency": "dependencies.scope",
    "observability.plan": "observability.plan",
    "observability": "observability.plan",
    "monitoring": "observability.plan",
}


def _effective_outputs(
    round1_outputs: list[ReviewerOutput], round2_outputs: list[ReviewerOutput]
) -> list[ReviewerOutput]:
    return round2_outputs or round1_outputs


def _canonical_clause_key(clause: str) -> str | None:
    normalized = re.sub(r"[\s_-]+", ".", clause.strip().lower())
    normalized = re.sub(r"\.+", ".", normalized).strip(".")
    if re.fullmatch(r"acceptance\.\d+", normalized):
        return "acceptance.criteria"
    return CLAUSE_KEY_ALIASES.get(normalized)


def _normalized_per_clause(output: ReviewerOutput) -> tuple[dict[str, ClauseStatus], list[str]]:
    normalized: dict[str, ClauseStatus] = {}
    unknown: list[str] = []
    for clause, status in output.per_clause.items():
        canonical = _canonical_clause_key(clause)
        if canonical is None:
            unknown.append(clause)
            continue
        normalized[canonical] = status
    return normalized, unknown


def _find_contradictions(
    outputs: list[ReviewerOutput],
) -> tuple[list[ContradictionFinding], list[str]]:
    positions_by_clause: dict[str, dict[str, ClauseStatus]] = defaultdict(dict)
    unknown_clause_warnings: list[str] = []
    for output in outputs:
        normalized, unknown = _normalized_per_clause(output)
        for clause in unknown:
            unknown_clause_warnings.append(
                f"Unknown per_clause key from {output.reviewer} ignored: {clause}"
            )
        for clause, status in normalized.items():
            if status != ClauseStatus.NA:
                positions_by_clause[clause][output.reviewer] = status

    contradictions: list[ContradictionFinding] = []
    for clause, positions in sorted(positions_by_clause.items()):
        distinct = set(positions.values())
        if len(distinct) <= 1:
            continue
        severity = (
            "high"
            if {ClauseStatus.SATISFIED, ClauseStatus.UNSATISFIED}.issubset(distinct)
            else "medium"
        )
        contradictions.append(
            ContradictionFinding(
                clause_id=clause,
                reviewer_positions=positions,
                severity=severity,
            )
        )
    return contradictions, unknown_clause_warnings


def _round2_report(
    reviewers_used: list[str],
    round1_outputs: list[ReviewerOutput],
    round2_outputs: list[ReviewerOutput],
) -> tuple[int | None, list[Round2Comparison]]:
    if not round2_outputs:
        return None, []
    round1_by_reviewer = {output.reviewer: output.verdict for output in round1_outputs}
    round2_by_reviewer = {output.reviewer: output.verdict for output in round2_outputs}

    comparisons: list[Round2Comparison] = []
    for reviewer in reviewers_used:
        round1 = round1_by_reviewer.get(reviewer)
        round2 = round2_by_reviewer.get(reviewer)
        comparable = round1 in COMPARABLE_ROUND2_VERDICTS and round2 in COMPARABLE_ROUND2_VERDICTS
        changed = (round1 != round2) if comparable else None
        comparisons.append(
            Round2Comparison(
                reviewer=reviewer,
                round1=round1,
                round2=round2,
                comparable=comparable,
                changed=changed,
            )
        )
    return sum(1 for comparison in comparisons if comparison.changed is True), comparisons


def _system_confidence(
    *,
    outputs: list[ReviewerOutput],
    non_abstained: list[ReviewerOutput],
    diversity: DiversityReport,
    singletons: list[object],
    contradictions: list[ContradictionFinding],
    collapsed_quorum: bool,
) -> float:
    if not non_abstained:
        return 0.0

    self_reported = mean(output.confidence for output in non_abstained)
    usable_ratio = len(non_abstained) / max(1, len(outputs))
    confidence = self_reported * usable_ratio

    if diversity.status == "low":
        confidence *= 0.75
    if contradictions:
        confidence *= 0.6
    elif singletons:
        confidence *= 0.85
    if collapsed_quorum:
        confidence = min(confidence, 0.25)

    return round(confidence, 3)


def reconcile(
    *,
    plan_path: str,
    plan_text: str,
    reviewers_used: list[str],
    round1_outputs: list[ReviewerOutput],
    round2_outputs: list[ReviewerOutput],
    diversity: DiversityReport | None = None,
) -> ReconciledVerdict:
    outputs = _effective_outputs(round1_outputs, round2_outputs)
    non_abstained = [output for output in outputs if output.verdict != Verdict.ABSTAIN]
    abstained = [output.reviewer for output in outputs if output.verdict == Verdict.ABSTAIN]
    diversity = diversity or analyze_reviewer_diversity(reviewers_used)
    collapsed_quorum = len(outputs) > 1 and 0 < len(non_abstained) < 2
    partial_quorum = len(outputs) > 1 and bool(abstained) and not collapsed_quorum

    issue_items = [
        (output.reviewer, issue)
        for output in non_abstained
        for issue in output.blocking_issues
    ]
    if os.getenv("KRYSTAL_QUORUM_CONSENSUS_MATCHER", "deterministic").lower() == "legacy":
        shared, singletons = legacy_group_issues(issue_items)
        issue_clusters: list[IssueCluster] = []
    else:
        issue_clusters = cluster_issues(issue_items)
        shared = [cluster.representative for cluster in issue_clusters if cluster.shared]
        singletons = [cluster.representative for cluster in issue_clusters if not cluster.shared]
    contradictions, unknown_clause_warnings = _find_contradictions(non_abstained)
    round2_delta, round2_comparisons = _round2_report(
        reviewers_used,
        round1_outputs,
        round2_outputs,
    )

    verdicts = [output.verdict for output in non_abstained]
    if not non_abstained:
        merged = Verdict.REVISE
    elif collapsed_quorum:
        merged = Verdict.REVISE
    elif shared or Verdict.BLOCK in verdicts:
        merged = Verdict.BLOCK
    elif singletons or contradictions or Verdict.REVISE in verdicts:
        merged = Verdict.REVISE
    else:
        merged = Verdict.APPROVE

    unresolved: list[str] = []
    if not non_abstained:
        unresolved.append("All reviewers abstained; no usable review signal was produced.")
    elif collapsed_quorum:
        unresolved.append(
            f"Quorum collapsed: only {len(non_abstained)} of {len(outputs)} reviewers "
            "produced usable output."
        )
    elif partial_quorum:
        unresolved.append(f"Partial quorum: {len(abstained)} of {len(outputs)} reviewers abstained.")
    for issue in singletons:
        unresolved.append(f"Singleton blocker: {issue.claim}")
    for contradiction in contradictions:
        unresolved.append(f"Contradiction on {contradiction.clause_id}: human triage required.")
    unresolved.extend(unknown_clause_warnings)

    confidence = _system_confidence(
        outputs=outputs,
        non_abstained=non_abstained,
        diversity=diversity,
        singletons=singletons,
        contradictions=contradictions,
        collapsed_quorum=collapsed_quorum,
    )
    return ReconciledVerdict(
        schema_version=SCHEMA_VERSION,
        plan_path=plan_path,
        plan_sha256=plan_sha256(plan_text),
        timestamp=datetime.now(timezone.utc).isoformat(),
        reviewers_used=reviewers_used,
        diversity=diversity,
        abstained_reviewers=abstained,
        merged_verdict=merged,
        confidence=confidence,
        shared_blocking_issues=shared,
        singleton_blocking_issues=singletons,
        issue_clusters=issue_clusters,
        contradictions=contradictions,
        unresolved_for_human=unresolved,
        round1_outputs=round1_outputs,
        round2_outputs=round2_outputs,
        round2_delta=round2_delta,
        round2_comparisons=round2_comparisons,
    )
