from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
import re

from krystal_quorum.models import (
    ClauseStatus,
    ContradictionFinding,
    DiversityReport,
    ReconciledVerdict,
    ReviewIssue,
    Round2Comparison,
    ReviewerOutput,
    Verdict,
)
from krystal_quorum.diversity import analyze_reviewer_diversity
from krystal_quorum.persist import plan_sha256

SCHEMA_VERSION = "1.1"
COMPARABLE_ROUND2_VERDICTS = {Verdict.APPROVE, Verdict.REVISE, Verdict.BLOCK}


def _effective_outputs(
    round1_outputs: list[ReviewerOutput], round2_outputs: list[ReviewerOutput]
) -> list[ReviewerOutput]:
    return round2_outputs or round1_outputs


def _fingerprint(issue: ReviewIssue) -> str:
    return " ".join(issue.claim.lower().split())[:80]


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "lacks",
    "missing",
    "no",
    "not",
    "of",
    "on",
    "or",
    "plan",
    "the",
    "to",
    "with",
}


def _issue_tokens(issue: ReviewIssue) -> set[str]:
    text = f"{issue.section} {issue.claim}".lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    return {token for token in tokens if len(token) > 2 and token not in STOPWORDS}


def _issues_match(left: ReviewIssue, right: ReviewIssue) -> bool:
    if _fingerprint(left) == _fingerprint(right):
        return True
    left_tokens = _issue_tokens(left)
    right_tokens = _issue_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    smaller = min(len(left_tokens), len(right_tokens))
    return overlap >= 3 and overlap / smaller >= 0.5


def _group_issues(outputs: list[ReviewerOutput]) -> tuple[list[ReviewIssue], list[ReviewIssue]]:
    grouped: list[tuple[ReviewIssue, set[str]]] = []
    for output in outputs:
        for issue in output.blocking_issues:
            for grouped_issue, reviewers in grouped:
                if _issues_match(grouped_issue, issue):
                    reviewers.add(output.reviewer)
                    break
            else:
                grouped.append((issue, {output.reviewer}))

    shared: list[ReviewIssue] = []
    singletons: list[ReviewIssue] = []
    for issue, reviewers in grouped:
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

    shared, singletons = _group_issues(non_abstained)
    contradictions = _find_contradictions(non_abstained)
    round2_delta, round2_comparisons = _round2_report(
        reviewers_used,
        round1_outputs,
        round2_outputs,
    )

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
        schema_version=SCHEMA_VERSION,
        plan_path=plan_path,
        plan_sha256=plan_sha256(plan_text),
        timestamp=datetime.now(timezone.utc).isoformat(),
        reviewers_used=reviewers_used,
        diversity=diversity or analyze_reviewer_diversity(reviewers_used),
        abstained_reviewers=abstained,
        merged_verdict=merged,
        confidence=confidence,
        shared_blocking_issues=shared,
        singleton_blocking_issues=singletons,
        contradictions=contradictions,
        unresolved_for_human=unresolved,
        round1_outputs=round1_outputs,
        round2_outputs=round2_outputs,
        round2_delta=round2_delta,
        round2_comparisons=round2_comparisons,
    )
