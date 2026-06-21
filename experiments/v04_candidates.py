from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from krystal_quorum.models import ClauseStatus, ReviewIssue, ReviewerOutput, Verdict
from krystal_quorum.reviewers.base import fallback_output, parse_reviewer_output


@dataclass(frozen=True)
class RetryProbe:
    output: ReviewerOutput
    attempts_used: int
    failed_attempts: tuple[str, ...]
    recovered: bool


def _is_parse_failure(output: ReviewerOutput) -> bool:
    return (
        output.verdict == Verdict.ABSTAIN
        and bool(output.blocking_issues)
        and output.blocking_issues[0].id == "B0"
        and "output unparseable" in output.blocking_issues[0].claim
    )


def try_repair_parse(
    reviewer: str,
    *,
    round_number: int,
    raw_attempts: list[str],
    elapsed_seconds: float = 0.0,
) -> RetryProbe:
    if not raw_attempts:
        output = fallback_output(
            reviewer,
            round_number,
            claim="reviewer produced no attempts",
            elapsed_seconds=elapsed_seconds,
        )
        return RetryProbe(output=output, attempts_used=0, failed_attempts=(), recovered=False)

    failed_attempts: list[str] = []
    last_output: ReviewerOutput | None = None
    for index, raw_response in enumerate(raw_attempts):
        output = parse_reviewer_output(
            reviewer=reviewer,
            round_number=round_number,
            raw_response=raw_response,
            elapsed_seconds=elapsed_seconds,
            retries=index,
        )
        last_output = output
        if not _is_parse_failure(output):
            return RetryProbe(
                output=output,
                attempts_used=index + 1,
                failed_attempts=tuple(failed_attempts),
                recovered=bool(failed_attempts),
            )
        failed_attempts.append(raw_response)

    assert last_output is not None
    return RetryProbe(
        output=last_output,
        attempts_used=len(raw_attempts),
        failed_attempts=tuple(failed_attempts),
        recovered=False,
    )


@dataclass(frozen=True)
class IssueCluster:
    topic: str
    representative_claim: str
    reviewers: tuple[str, ...]
    issues: tuple[ReviewIssue, ...]
    shared: bool


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "if",
    "in",
    "is",
    "it",
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

_CONCEPTS = {
    "acceptance": {
        "acceptance",
        "criteria",
        "definition",
        "done",
        "pass",
        "fail",
        "requirement",
    },
    "rollback": {"rollback", "backout", "revert", "undo", "restore", "fallback"},
    "tests": {"test", "tests", "testing", "pytest", "verification", "verify", "ci"},
    "security": {"security", "secret", "secrets", "auth", "permission", "privacy"},
    "dependencies": {"dependency", "dependencies", "package", "packages", "version"},
    "observability": {"observability", "log", "logs", "metric", "metrics", "monitor", "alert"},
}

_TOPIC_PRIORITY = (
    "rollback",
    "acceptance",
    "tests",
    "security",
    "dependencies",
    "observability",
)


def _tokens(text: str) -> set[str]:
    normalized = text.lower().replace("back-out", "backout").replace("back out", "backout")
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    canonical: set[str] = set()
    for token in tokens:
        if len(token) <= 2 or token in _STOPWORDS:
            continue
        canonical.add(_canonical_token(token))
    return canonical


def _canonical_token(token: str) -> str:
    for concept, aliases in _CONCEPTS.items():
        if token in aliases:
            return concept
    return token


def _issue_terms(issue: ReviewIssue) -> set[str]:
    return _tokens(f"{issue.section} {issue.claim} {issue.evidence}")


def _topic(terms: set[str]) -> str:
    for topic in _TOPIC_PRIORITY:
        if topic in terms:
            return topic
    return "general"


def _issues_match(left: ReviewIssue, right: ReviewIssue) -> bool:
    left_terms = _issue_terms(left)
    right_terms = _issue_terms(right)
    left_topic = _topic(left_terms)
    if left_topic == "general" or left_topic != _topic(right_terms):
        return False
    overlap = left_terms & right_terms
    return left_topic in overlap and len(overlap) >= 1


def candidate_issue_clusters(outputs: list[ReviewerOutput]) -> list[IssueCluster]:
    grouped: list[tuple[str, ReviewIssue, list[ReviewIssue], set[str]]] = []
    for output in outputs:
        if output.verdict == Verdict.ABSTAIN:
            continue
        for issue in output.blocking_issues:
            terms = _issue_terms(issue)
            issue_topic = _topic(terms)
            for _, representative, issues, reviewers in grouped:
                if _issues_match(representative, issue):
                    issues.append(issue)
                    reviewers.add(output.reviewer)
                    break
            else:
                grouped.append((issue_topic, issue, [issue], {output.reviewer}))

    clusters: list[IssueCluster] = []
    for issue_topic, representative, issues, reviewers in grouped:
        sorted_reviewers = tuple(sorted(reviewers))
        clusters.append(
            IssueCluster(
                topic=issue_topic,
                representative_claim=representative.claim,
                reviewers=sorted_reviewers,
                issues=tuple(issues),
                shared=len(sorted_reviewers) >= 2,
            )
        )
    return clusters


@dataclass(frozen=True)
class ConfidenceSignals:
    total_reviewers: int
    non_abstained: int
    diversity_status: Literal["ok", "low"]
    shared_blockers: int
    singleton_blockers: int
    contradictions: int
    round2_delta: int | None


def candidate_confidence(signals: ConfidenceSignals) -> float:
    if signals.total_reviewers <= 0:
        return 0.0

    participation = max(0.0, min(1.0, signals.non_abstained / signals.total_reviewers))
    confidence = 0.25 + 0.45 * participation
    confidence += min(0.15, 0.08 * signals.shared_blockers)
    confidence -= min(0.18, 0.06 * signals.singleton_blockers)
    confidence -= min(0.22, 0.11 * signals.contradictions)
    if signals.diversity_status == "low":
        confidence -= 0.14
    if signals.round2_delta:
        confidence -= min(0.12, 0.04 * signals.round2_delta)
    return round(max(0.0, min(1.0, confidence)), 3)


@dataclass(frozen=True)
class RubricFinding:
    key: str
    status: ClauseStatus
    claim: str
    evidence: str


@dataclass(frozen=True)
class _RubricRule:
    key: str
    label: str
    terms: tuple[str, ...]
    missing_status: ClauseStatus


_RUBRIC_RULES = (
    _RubricRule(
        key="acceptance.criteria",
        label="Acceptance criteria",
        terms=("acceptance", "criteria", "done when", "pass/fail", "requirement"),
        missing_status=ClauseStatus.UNSATISFIED,
    ),
    _RubricRule(
        key="rollback.plan",
        label="Rollback plan",
        terms=("rollback", "backout", "revert", "feature flag", "previous"),
        missing_status=ClauseStatus.UNSATISFIED,
    ),
    _RubricRule(
        key="tests.verification",
        label="Tests and verification",
        terms=("test", "tests", "pytest", "verify", "verification", "ci"),
        missing_status=ClauseStatus.UNSATISFIED,
    ),
    _RubricRule(
        key="security.risk",
        label="Security risk",
        terms=("security", "secret", "secrets", "permission", "auth", "privacy"),
        missing_status=ClauseStatus.UNCLEAR,
    ),
    _RubricRule(
        key="dependencies.scope",
        label="Dependency scope",
        terms=("dependencies", "dependency", "package", "packages", "version"),
        missing_status=ClauseStatus.UNCLEAR,
    ),
    _RubricRule(
        key="observability.plan",
        label="Observability plan",
        terms=("observability", "log", "logs", "metric", "metrics", "monitor", "alert"),
        missing_status=ClauseStatus.UNCLEAR,
    ),
)


def _matched_term(plan_text: str, terms: tuple[str, ...]) -> str | None:
    lower = plan_text.lower()
    for term in terms:
        if term in lower:
            return term
    return None


def evaluate_rubric(plan_text: str) -> list[RubricFinding]:
    findings: list[RubricFinding] = []
    for rule in _RUBRIC_RULES:
        matched = _matched_term(plan_text, rule.terms)
        if matched:
            findings.append(
                RubricFinding(
                    key=rule.key,
                    status=ClauseStatus.SATISFIED,
                    claim=f"{rule.label} is present.",
                    evidence=f"Matched rubric signal: {matched}",
                )
            )
        else:
            findings.append(
                RubricFinding(
                    key=rule.key,
                    status=rule.missing_status,
                    claim=f"{rule.label} is not explicit.",
                    evidence="No matching rubric signal found.",
                )
            )
    return findings
