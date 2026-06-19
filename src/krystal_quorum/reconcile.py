from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from krystal_quorum.models import (
    ClauseStatus,
    ContradictionFinding,
    ReconciledVerdict,
    ReviewIssue,
    ReviewerOutput,
    Verdict,
)
from krystal_quorum.persist import plan_sha256


def _effective_outputs(
    round1_outputs: list[ReviewerOutput], round2_outputs: list[ReviewerOutput]
) -> list[ReviewerOutput]:
    return round2_outputs or round1_outputs


def _fingerprint(issue: ReviewIssue) -> str:
    return " ".join(issue.claim.lower().split())[:80]


def _group_issues(outputs: list[ReviewerOutput]) -> tuple[list[ReviewIssue], list[ReviewIssue]]:
    grouped: dict[str, tuple[ReviewIssue, set[str]]] = {}
    for output in outputs:
        for issue in output.blocking_issues:
            key = _fingerprint(issue)
            if key not in grouped:
                grouped[key] = (issue, set())
            grouped[key][1].add(output.reviewer)

    shared: list[ReviewIssue] = []
    singletons: list[ReviewIssue] = []
    for issue, reviewers in grouped.values():
        if len(reviewers) >= 2:
            shared.append(issue)
        else:
            singletons.append(issue)
    return shared, singletons


def _find_contradictions(outputs: list[ReviewerOutput]) -> list[ContradictionFinding]:
    positions_by_clause: dict[str, dict[str, ClauseStatus]] = defaultdict(dict)
    for output in outputs:
        for clause, status in output.per_clause.items():
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
    return contradictions


def reconcile(
    *,
    plan_path: str,
    plan_text: str,
    reviewers_used: list[str],
    round1_outputs: list[ReviewerOutput],
    round2_outputs: list[ReviewerOutput],
) -> ReconciledVerdict:
    outputs = _effective_outputs(round1_outputs, round2_outputs)
    non_abstained = [output for output in outputs if output.verdict != Verdict.ABSTAIN]
    abstained = [output.reviewer for output in outputs if output.verdict == Verdict.ABSTAIN]

    shared, singletons = _group_issues(non_abstained)
    contradictions = _find_contradictions(non_abstained)

    verdicts = [output.verdict for output in non_abstained]
    if not non_abstained:
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
    for issue in singletons:
        unresolved.append(f"Singleton blocker: {issue.claim}")
    for contradiction in contradictions:
        unresolved.append(f"Contradiction on {contradiction.clause_id}: human triage required.")

    confidence = mean(output.confidence for output in non_abstained) if non_abstained else 0.0
    return ReconciledVerdict(
        plan_path=plan_path,
        plan_sha256=plan_sha256(plan_text),
        timestamp=datetime.now(timezone.utc).isoformat(),
        reviewers_used=reviewers_used,
        abstained_reviewers=abstained,
        merged_verdict=merged,
        confidence=confidence,
        shared_blocking_issues=shared,
        singleton_blocking_issues=singletons,
        contradictions=contradictions,
        unresolved_for_human=unresolved,
        round1_outputs=round1_outputs,
        round2_outputs=round2_outputs,
    )
