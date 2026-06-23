from __future__ import annotations

from dataclasses import dataclass
import re

from krystal_quorum.models import (
    IssueCluster,
    IssueClusterEdge,
    IssueClusterMember,
    ReviewIssue,
)

TOPIC_ALIASES = {
    "acceptance": {
        "acceptance",
        "criterion",
        "criteria",
        "done",
        "pass",
        "fail",
        "requirement",
    },
    "rollback": {
        "rollback",
        "backout",
        "revert",
        "undo",
        "restore",
        "fallback",
        "featureflag",
    },
    "tests": {
        "test",
        "tests",
        "testing",
        "pytest",
        "verification",
        "verify",
        "ci",
        "smoke",
    },
    "security": {
        "security",
        "secret",
        "secrets",
        "auth",
        "permission",
        "privacy",
    },
    "dependencies": {
        "dependency",
        "dependencies",
        "package",
        "packages",
        "version",
    },
    "observability": {
        "observability",
        "log",
        "logs",
        "metric",
        "metrics",
        "monitor",
        "alert",
    },
}

TOPIC_GAP_ALIASES = {
    "acceptance": {
        "criteria": "criteria",
        "criterion": "criteria",
        "done": "criteria",
        "requirement": "criteria",
        "pass": "criteria",
        "fail": "criteria",
    },
    "rollback": {
        "rollback": "recovery",
        "backout": "recovery",
        "revert": "recovery",
        "restore": "recovery",
        "fallback": "recovery",
        "path": "recovery",
        "failure": "failure",
        "fails": "failure",
        "deployment": "deployment",
        "featureflag": "featureflag",
    },
    "tests": {
        "test": "verification",
        "tests": "verification",
        "testing": "verification",
        "pytest": "verification",
        "verify": "verification",
        "verification": "verification",
        "ci": "ci",
        "smoke": "smoke",
        "command": "command",
    },
    "security": {
        "auth": "permission",
        "permission": "permission",
        "permissions": "permission",
        "secret": "secret",
        "secrets": "secret",
        "audit": "audit",
        "logging": "logging",
        "log": "logging",
        "export": "export",
    },
    "dependencies": {
        "dependency": "dependency",
        "dependencies": "dependency",
        "package": "package",
        "packages": "package",
        "version": "version",
        "pin": "version",
    },
    "observability": {
        "observability": "observability",
        "log": "logging",
        "logs": "logging",
        "metric": "metric",
        "metrics": "metric",
        "monitor": "monitoring",
        "alert": "alerting",
    },
}

TOPIC_BY_ALIAS = {
    alias: topic for topic, aliases in TOPIC_ALIASES.items() for alias in aliases
}

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
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}

LEGACY_STOPWORDS = {
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

GENERIC_REVIEW_TERMS = {
    "claim",
    "described",
    "description",
    "evidence",
    "finding",
    "findings",
    "gap",
    "gaps",
    "issue",
    "issues",
    "missing",
    "no",
    "not",
    "omits",
    "omitted",
    "plan",
    "risk",
    "review",
    "reviewer",
    "section",
    "unclear",
    "undefined",
    "without",
}

ABSENCE_TERMS = {
    "absent",
    "lack",
    "lacks",
    "missing",
    "no",
    "not",
    "omits",
    "omitted",
    "undefined",
    "without",
}

MIN_SUPPORT_OVERLAP = 2
MIN_OVERLAP_COEFFICIENT = 0.50


@dataclass(frozen=True)
class IssueMatchInput:
    reviewer: str
    issue: ReviewIssue


@dataclass(frozen=True)
class _AnalyzedIssue:
    index: int
    source: IssueMatchInput
    topic: str
    support_terms: set[str]
    gap_terms: set[str]
    absence_terms: set[str]
    fingerprint: str


@dataclass(frozen=True)
class _MatchEdge:
    left_index: int
    right_index: int
    reason: str


def _fingerprint(issue: ReviewIssue) -> str:
    return " ".join(issue.claim.lower().split())[:80]


def _normalize_text(text: str) -> str:
    return (
        text.lower()
        .replace("back-out", "backout")
        .replace("back out", "backout")
        .replace("feature flag", "featureflag")
        .replace("feature-flag", "featureflag")
    )


def _raw_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_text(text))


def _canonical_token(token: str) -> str:
    return TOPIC_BY_ALIAS.get(token, token)


def _score_topic(issue: ReviewIssue) -> str:
    scores = {topic: 0 for topic in TOPIC_ALIASES}
    for token in _raw_tokens(issue.section):
        if topic := TOPIC_BY_ALIAS.get(token):
            scores[topic] += 2
    for token in _raw_tokens(issue.claim):
        if topic := TOPIC_BY_ALIAS.get(token):
            scores[topic] += 1
        for gap_topic, aliases in TOPIC_GAP_ALIASES.items():
            if token in aliases:
                scores[gap_topic] += 1
    for token in _raw_tokens(issue.evidence):
        if topic := TOPIC_BY_ALIAS.get(token):
            scores[topic] += 1
        for gap_topic, aliases in TOPIC_GAP_ALIASES.items():
            if token in aliases:
                scores[gap_topic] += 1
    highest = max(scores.values())
    if highest == 0:
        return "general"
    winners = [topic for topic, score in scores.items() if score == highest]
    return winners[0] if len(winners) == 1 else "general"


def _gap_terms(topic: str, tokens: list[str]) -> set[str]:
    aliases = TOPIC_GAP_ALIASES.get(topic, {})
    return {aliases[token] for token in tokens if token in aliases}


def _support_terms(topic: str, tokens: list[str]) -> set[str]:
    canonical = {_canonical_token(token) for token in tokens if len(token) > 2}
    return {
        term
        for term in canonical
        if term not in STOPWORDS
        and term not in GENERIC_REVIEW_TERMS
        and term not in ABSENCE_TERMS
        and term != topic
    }


def _analyze(index: int, source: IssueMatchInput) -> _AnalyzedIssue:
    issue = source.issue
    text = f"{issue.section} {issue.claim} {issue.evidence}"
    tokens = _raw_tokens(text)
    topic = _score_topic(issue)
    return _AnalyzedIssue(
        index=index,
        source=source,
        topic=topic,
        support_terms=_support_terms(topic, tokens),
        gap_terms=_gap_terms(topic, tokens),
        absence_terms={token for token in tokens if token in ABSENCE_TERMS},
        fingerprint=_fingerprint(issue),
    )


def _match_reason(left: _AnalyzedIssue, right: _AnalyzedIssue) -> str | None:
    if left.source.reviewer == right.source.reviewer:
        return None
    if left.fingerprint == right.fingerprint:
        return "exact fingerprint match"
    if left.topic != right.topic or left.topic == "general":
        return None

    shared_gap = sorted(left.gap_terms & right.gap_terms)
    if left.absence_terms and right.absence_terms and shared_gap:
        return (
            f"shared topic {left.topic} with absence intent; "
            f"gap overlap: {', '.join(shared_gap)}"
        )

    shared_support = sorted(left.support_terms & right.support_terms)
    smaller = min(len(left.support_terms), len(right.support_terms))
    if smaller == 0:
        return None
    coefficient = len(shared_support) / smaller
    if (
        len(shared_support) >= MIN_SUPPORT_OVERLAP
        and coefficient >= MIN_OVERLAP_COEFFICIENT
    ):
        return (
            f"shared topic {left.topic} with overlap coefficient {coefficient:.2f}; "
            f"supporting overlap: {', '.join(shared_support)}"
        )
    return None


def _member(item: _AnalyzedIssue) -> IssueClusterMember:
    issue = item.source.issue
    return IssueClusterMember(
        reviewer=item.source.reviewer,
        issue_id=issue.id,
        section=issue.section,
        claim=issue.claim,
    )


def _edge(left: _AnalyzedIssue, right: _AnalyzedIssue, reason: str) -> IssueClusterEdge:
    return IssueClusterEdge(
        left_reviewer=left.source.reviewer,
        left_issue_id=left.source.issue.id,
        right_reviewer=right.source.reviewer,
        right_issue_id=right.source.issue.id,
        match_reason=reason,
    )


def _connected_components(count: int, edges: list[_MatchEdge]) -> list[list[int]]:
    adjacency = {index: set() for index in range(count)}
    for edge in edges:
        adjacency[edge.left_index].add(edge.right_index)
        adjacency[edge.right_index].add(edge.left_index)

    seen: set[int] = set()
    components: list[list[int]] = []
    for index in range(count):
        if index in seen:
            continue
        stack = [index]
        component: list[int] = []
        seen.add(index)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))
    return components


def cluster_issues(items: list[tuple[str, ReviewIssue]]) -> list[IssueCluster]:
    analyzed = [
        _analyze(index, IssueMatchInput(reviewer, issue))
        for index, (reviewer, issue) in enumerate(items)
    ]
    edges: list[_MatchEdge] = []
    for left_index, left in enumerate(analyzed):
        for right in analyzed[left_index + 1 :]:
            if reason := _match_reason(left, right):
                edges.append(_MatchEdge(left.index, right.index, reason))

    clusters: list[IssueCluster] = []
    for component in _connected_components(len(analyzed), edges):
        members = [analyzed[index] for index in component]
        component_edges = [
            edge
            for edge in edges
            if edge.left_index in component and edge.right_index in component
        ]
        reviewers = sorted({member.source.reviewer for member in members})
        edge_models = [
            _edge(analyzed[edge.left_index], analyzed[edge.right_index], edge.reason)
            for edge in component_edges
        ]
        match_reason = (
            edge_models[0].match_reason
            if edge_models
            else "singleton; no deterministic consensus match"
        )
        clusters.append(
            IssueCluster(
                topic=members[0].topic,
                shared=len(reviewers) >= 2 and bool(edge_models),
                reviewers=reviewers,
                representative=members[0].source.issue,
                members=[_member(member) for member in members],
                edges=edge_models,
                match_reason=match_reason,
            )
        )
    return clusters


def legacy_group_issues(
    items: list[tuple[str, ReviewIssue]],
) -> tuple[list[ReviewIssue], list[ReviewIssue]]:
    grouped: list[tuple[ReviewIssue, set[str]]] = []
    for reviewer, issue in items:
        for grouped_issue, reviewers in grouped:
            if _legacy_issues_match(grouped_issue, issue):
                reviewers.add(reviewer)
                break
        else:
            grouped.append((issue, {reviewer}))

    shared: list[ReviewIssue] = []
    singletons: list[ReviewIssue] = []
    for issue, reviewers in grouped:
        if len(reviewers) >= 2:
            shared.append(issue)
        else:
            singletons.append(issue)
    return shared, singletons


def _legacy_issue_tokens(issue: ReviewIssue) -> set[str]:
    text = f"{issue.section} {issue.claim}".lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    return {token for token in tokens if len(token) > 2 and token not in LEGACY_STOPWORDS}


def _legacy_issues_match(left: ReviewIssue, right: ReviewIssue) -> bool:
    if _fingerprint(left) == _fingerprint(right):
        return True
    left_tokens = _legacy_issue_tokens(left)
    right_tokens = _legacy_issue_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    smaller = min(len(left_tokens), len(right_tokens))
    return overlap >= 3 and overlap / smaller >= 0.5
