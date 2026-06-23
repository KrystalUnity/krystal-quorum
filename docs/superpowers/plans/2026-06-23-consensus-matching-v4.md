# Consensus Matching V4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote genuinely matching reviewer findings into shared blockers using deterministic pairwise match edges, while preventing broad absence-word false positives and preserving backward compatibility for existing artifacts.

**Architecture:** Add `issue_matching.py` as a graph-style matcher: every issue pair is scored, accepted matches become explicit edges, and issue clusters are connected components of those edges. Reconciliation persists schema `1.2` with `issue_clusters`, can fall back to legacy grouping using `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy`, and keeps old `ReconciledVerdict` construction/deserialization compatible with `Field(default_factory=list)`.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, existing Krystal Quorum CLI and reconciliation flow.

---

## V3 Fixes From V2 Quorum Block

The V2 review blocked on three precise issues. V3 resolves them as follows:

1. **Greedy clustering bug**
   - V2 compared candidates only against `group[0]`.
   - V3 builds pairwise match edges across all issue pairs, then clusters connected components. A new issue can join a cluster by matching any existing member.

2. **Absence-intent false positives**
   - V2 matched same-topic findings if both contained any absence word.
   - V3 requires absence intent plus at least one shared topic-specific gap term, such as rollback `recovery`, security `permission`, tests `verification`, or observability `logging`.

3. **Breaking `issue_clusters` field**
   - V2 added `issue_clusters` without a default.
   - V3 uses `Field(default_factory=list)`, so existing constructors and old schema `1.1` artifacts still validate.

## V4 Fixes From V3 Quorum Block

The V3 review blocked on one test/contract mismatch. V4 resolves it with two exact changes:

1. **Topic scoring uses gap aliases**
   - V3 scored topic only from broad `TOPIC_ALIASES`, so "Deployment failure handling is absent" became `general`.
   - V4 also scores a topic when tokens appear in that topic's gap alias table. Claim/evidence gap hits add `+1`; section gap hits add `+2`.

2. **Connected-component fixture is internally consistent**
   - V3's three-reviewer fixture accidentally made A match C once C was treated as rollback.
   - V4 changes C to "Deployment failure handling is absent" and removes `strategy` / `procedure` as rollback `recovery` gap aliases. Now A-B share `recovery`, B-C share `deployment` and `failure`, and A-C shares no gap term.

## File Map

- Create: `src/krystal_quorum/issue_matching.py`
  - Owns tokenization, topic selection, gap-term selection, pairwise match edges, connected-component clustering, and legacy grouping.
- Modify: `src/krystal_quorum/models.py`
  - Add `IssueClusterMember`, `IssueClusterEdge`, and `IssueCluster`.
  - Add `issue_clusters: list[IssueCluster] = Field(default_factory=list)` to `ReconciledVerdict`.
- Modify: `src/krystal_quorum/reconcile.py`
  - Bump `SCHEMA_VERSION` to `1.2`.
  - Use deterministic clusters by default.
  - Use legacy grouping when `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy`.
- Modify: `src/krystal_quorum/persist.py`
  - Render `Issue Clusters` in `summary.md`, including match edges.
- Create: `tests/test_issue_matching.py`
  - Unit tests for pairwise edges, connected components, absence guardrails, same-reviewer handling, and `general` fallback.
- Modify: `tests/test_models.py`
  - Tests for cluster models and backward-compatible default field.
- Modify: `tests/test_reconcile.py`
  - Integration tests for default deterministic mode and legacy rollback mode.
- Modify: `tests/test_persist.py`
  - Tests that `reconciled.json` and `summary.md` expose cluster reasons.
- Modify: `README.md`
  - Document deterministic consensus matching and rollback mode.
- Modify: `docs/v0.4-experiment-report.md`
  - Mark consensus matching as promoted only after implementation and review pass.

## Exact Matching Contract

### Topic Aliases

```python
TOPIC_ALIASES = {
    "acceptance": {
        "acceptance", "criterion", "criteria", "done", "pass", "fail", "requirement",
    },
    "rollback": {
        "rollback", "backout", "revert", "undo", "restore", "fallback", "featureflag",
    },
    "tests": {
        "test", "tests", "testing", "pytest", "verification", "verify", "ci", "smoke",
    },
    "security": {
        "security", "secret", "secrets", "auth", "permission", "privacy",
    },
    "dependencies": {
        "dependency", "dependencies", "package", "packages", "version",
    },
    "observability": {
        "observability", "log", "logs", "metric", "metrics", "monitor", "alert",
    },
}
```

Topic selection:

- Section alias hit: `+2`
- Claim alias hit: `+1`
- Evidence alias hit: `+1`
- Section gap alias hit: `+2`
- Claim gap alias hit: `+1`
- Evidence gap alias hit: `+1`
- Highest score `0` means topic `general`.
- Tied highest score means topic `general`.

### Topic Gap Terms

Gap terms are topic-specific and separate from broad topic aliases. They are used to make absence matches precise.

```python
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
        "plan": "recovery",
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
```

Examples:

- "No rollback plan is described." -> topic `rollback`, gap terms `{recovery}`
- "Missing backout path if deployment fails." -> topic `rollback`, gap terms `{recovery, deployment, failure}`
- "Deployment failure handling is absent." -> topic `rollback`, gap terms `{deployment, failure}`
- "No security audit is scheduled." -> topic `security`, gap terms `{audit}`
- "Missing security logging for exports." -> topic `security`, gap terms `{logging, export}`

The first two rollback issues match by shared gap term `recovery`. The second and third rollback issues match by shared gap terms `deployment` and `failure`. The first and third rollback issues do not match because they share no gap term. The two security issues do not match by absence intent because they share no gap term.

### Pairwise Match Rule

Two issues match only when:

1. Reviewer IDs differ.
2. Exact fingerprint matches, or the deterministic rules below match.
3. Both issues have the same topic.
4. Topic is not `general`.
5. One of these same-topic conditions is true:
   - both issues have absence intent and share at least one topic-specific gap term;
   - support-term overlap coefficient is `>= 0.50` and there is at least one shared support term.

Overlap coefficient:

```python
len(shared_support_terms) / min(len(left_support_terms), len(right_support_terms))
```

`support_terms` exclude:

- stopwords
- generic review terms
- absence terms
- the canonical topic token

### Match Edges And Clusters

Every accepted pairwise match creates an edge:

```python
IssueClusterEdge(
    left_reviewer="agy",
    left_issue_id="B1",
    right_reviewer="claude",
    right_issue_id="B2",
    match_reason="shared topic rollback with absence intent; gap overlap: recovery",
)
```

Clusters are connected components of these edges. This fixes the V2 representative-only bug:

- A does not match C.
- A matches B.
- B matches C.
- A, B, and C become one connected cluster with two visible match edges.

Singleton issues become clusters with:

```python
shared=False
match_reason="singleton; no deterministic consensus match"
edges=[]
```

## Acceptance Criteria

Implementation is complete only when all are true:

- `python -m pytest tests/test_issue_matching.py -q` passes.
- `python -m pytest tests/test_models.py tests/test_reconcile.py tests/test_persist.py -q` passes.
- `python -m pytest -q` passes.
- `python -m ruff check .` passes.
- Three-reviewer connected-component test passes where C joins by matching B, not representative A, and exactly two edges are produced.
- Absence false-positive test passes for "No security audit" vs "Missing security logging".
- Rollback/backout absence test passes by shared gap term `recovery`.
- `ReconciledVerdict.model_validate(...)` accepts an old schema `1.1` payload without `issue_clusters`.
- `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy` preserves old singleton behavior for rollback/backout paraphrases.
- `reconciled.json` includes `schema_version: "1.2"` and `issue_clusters[*].edges`.
- `summary.md` includes cluster match reasons and edge reasons.

## Rollback Plan

If deterministic matching regresses behavior:

1. Set `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy`.
2. Re-run Quorum against the affected plan.
3. Confirm `issue_clusters` is empty and grouping behavior matches legacy `1.1` behavior.
4. Revert the implementation commit if a release rollback is needed.

---

### Task 1: Add Backward-Compatible Issue Cluster Models

**Files:**

- Modify: `src/krystal_quorum/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Add this to `tests/test_models.py`:

```python
from krystal_quorum.models import (
    IssueCluster,
    IssueClusterEdge,
    IssueClusterMember,
    ReconciledVerdict,
    ReviewIssue,
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_models.py::test_issue_cluster_accepts_edge_payload tests/test_models.py::test_reconciled_verdict_defaults_issue_clusters_for_old_payload -q
```

Expected: import failure for the new cluster classes.

- [ ] **Step 3: Add model classes and default**

Add these imports/fields in `src/krystal_quorum/models.py`:

```python
from pydantic import BaseModel, ConfigDict, Field
```

Add after `ContradictionFinding`:

```python
class IssueClusterMember(StrictModel):
    reviewer: str
    issue_id: str
    section: str
    claim: str


class IssueClusterEdge(StrictModel):
    left_reviewer: str
    left_issue_id: str
    right_reviewer: str
    right_issue_id: str
    match_reason: str


class IssueCluster(StrictModel):
    topic: str
    shared: bool
    reviewers: list[str]
    representative: ReviewIssue
    members: list[IssueClusterMember]
    edges: list[IssueClusterEdge] = Field(default_factory=list)
    match_reason: str
```

Add after `singleton_blocking_issues` in `ReconciledVerdict`:

```python
    issue_clusters: list[IssueCluster] = Field(default_factory=list)
```

- [ ] **Step 4: Run model tests**

Run:

```bash
python -m pytest tests/test_models.py -q
```

Expected: all model tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/krystal_quorum/models.py tests/test_models.py
git commit -m "feat: add issue cluster artifact models"
```

### Task 2: Add Edge-Based Deterministic Matcher

**Files:**

- Create: `src/krystal_quorum/issue_matching.py`
- Create: `tests/test_issue_matching.py`

- [ ] **Step 1: Write failing matcher tests**

Create `tests/test_issue_matching.py`:

```python
from krystal_quorum.issue_matching import cluster_issues
from krystal_quorum.models import ReviewIssue


def issue(id: str, claim: str, section: str = "Plan", evidence: str = "evidence") -> ReviewIssue:
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
            ("glm", issue("B1", "Security permission checks for admin export are missing.")),
            ("claude", issue("B2", "Auth permission checks for admin export are undefined.")),
        ]
    )

    cluster = shared(clusters)[0]

    assert cluster.topic == "security"
    assert "overlap coefficient" in cluster.match_reason
    assert "supporting overlap" in cluster.match_reason


def test_ambiguous_tied_topic_becomes_general():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "Rollback security test is missing.")),
            ("claude", issue("B2", "Security rollback test is missing.")),
        ]
    )

    assert clusters[0].topic == "general"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_issue_matching.py -q
```

Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement matcher**

Create `src/krystal_quorum/issue_matching.py`:

```python
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
        "acceptance", "criterion", "criteria", "done", "pass", "fail", "requirement",
    },
    "rollback": {
        "rollback", "backout", "revert", "undo", "restore", "fallback", "featureflag",
    },
    "tests": {
        "test", "tests", "testing", "pytest", "verification", "verify", "ci", "smoke",
    },
    "security": {
        "security", "secret", "secrets", "auth", "permission", "privacy",
    },
    "dependencies": {
        "dependency", "dependencies", "package", "packages", "version",
    },
    "observability": {
        "observability", "log", "logs", "metric", "metrics", "monitor", "alert",
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
        "plan": "recovery",
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

TOPIC_BY_ALIAS = {alias: topic for topic, aliases in TOPIC_ALIASES.items() for alias in aliases}
STOPWORDS = {
    "a", "an", "and", "are", "as", "be", "but", "by", "for", "from",
    "has", "have", "if", "in", "into", "is", "it", "its", "of", "on",
    "or", "that", "the", "this", "to", "with",
}
GENERIC_REVIEW_TERMS = {
    "claim", "evidence", "finding", "findings", "gap", "gaps", "issue",
    "issues", "missing", "no", "not", "omits", "omitted", "risk",
    "review", "reviewer", "section", "unclear", "undefined", "without",
}
ABSENCE_TERMS = {
    "no", "missing", "lacks", "lack", "omits", "omitted", "absent", "without",
}
MIN_SUPPORT_OVERLAP = 1
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
        for gap_topic, aliases in TOPIC_GAP_ALIASES.items():
            if token in aliases:
                scores[gap_topic] += 2
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
    if len(shared_support) >= MIN_SUPPORT_OVERLAP and coefficient >= MIN_OVERLAP_COEFFICIENT:
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
    analyzed = [_analyze(index, IssueMatchInput(reviewer, issue)) for index, (reviewer, issue) in enumerate(items)]
    edges: list[_MatchEdge] = []
    for left_index, left in enumerate(analyzed):
        for right in analyzed[left_index + 1 :]:
            if reason := _match_reason(left, right):
                edges.append(_MatchEdge(left.index, right.index, reason))

    clusters: list[IssueCluster] = []
    for component in _connected_components(len(analyzed), edges):
        members = [analyzed[index] for index in component]
        component_edges = [
            edge for edge in edges if edge.left_index in component and edge.right_index in component
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


def legacy_group_issues(items: list[tuple[str, ReviewIssue]]) -> tuple[list[ReviewIssue], list[ReviewIssue]]:
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
    return {token for token in tokens if len(token) > 2 and token not in STOPWORDS}


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
```

- [ ] **Step 4: Run focused matcher tests**

Run:

```bash
python -m pytest tests/test_issue_matching.py -q
```

Expected: all matcher tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/krystal_quorum/issue_matching.py tests/test_issue_matching.py
git commit -m "feat: add edge-based issue matcher"
```

### Task 3: Integrate Matcher Into Reconciliation

**Files:**

- Modify: `src/krystal_quorum/reconcile.py`
- Modify: `tests/test_reconcile.py`

- [ ] **Step 1: Add failing reconciliation tests**

Add this to `tests/test_reconcile.py`:

```python
def test_reconcile_promotes_rollback_backout_consensus():
    issue_a = ReviewIssue(id="B1", section="Plan", claim="No rollback plan is described.", evidence="")
    issue_b = ReviewIssue(id="B2", section="Plan", claim="Missing backout path if deployment fails.", evidence="")

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["agy", "claude"],
        round1_outputs=[
            output("agy", Verdict.REVISE, issue_a),
            output("claude", Verdict.REVISE, issue_b),
        ],
        round2_outputs=[],
    )

    assert result.schema_version == "1.2"
    assert result.merged_verdict == Verdict.BLOCK
    assert len(result.shared_blocking_issues) == 1
    assert result.singleton_blocking_issues == []
    assert result.issue_clusters[0].edges[0].match_reason == (
        "shared topic rollback with absence intent; gap overlap: recovery"
    )


def test_reconcile_legacy_matcher_env_rolls_back_consensus(monkeypatch):
    monkeypatch.setenv("KRYSTAL_QUORUM_CONSENSUS_MATCHER", "legacy")
    issue_a = ReviewIssue(id="B1", section="Plan", claim="No rollback plan is described.", evidence="")
    issue_b = ReviewIssue(id="B2", section="Plan", claim="Missing backout path if deployment fails.", evidence="")

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["agy", "claude"],
        round1_outputs=[
            output("agy", Verdict.REVISE, issue_a),
            output("claude", Verdict.REVISE, issue_b),
        ],
        round2_outputs=[],
    )

    assert result.schema_version == "1.2"
    assert result.shared_blocking_issues == []
    assert len(result.singleton_blocking_issues) == 2
    assert result.issue_clusters == []
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_reconcile.py::test_reconcile_promotes_rollback_backout_consensus tests/test_reconcile.py::test_reconcile_legacy_matcher_env_rolls_back_consensus -q
```

Expected: fails because reconciliation still uses schema `1.1` and old grouping.

- [ ] **Step 3: Modify reconciliation**

In `src/krystal_quorum/reconcile.py`:

1. Add `import os`.
2. Import `cluster_issues` and `legacy_group_issues`.
3. Change `SCHEMA_VERSION = "1.2"`.
4. Replace `_group_issues(non_abstained)` with:

```python
    issue_items = [
        (output.reviewer, issue)
        for output in non_abstained
        for issue in output.blocking_issues
    ]
    if os.getenv("KRYSTAL_QUORUM_CONSENSUS_MATCHER", "deterministic").lower() == "legacy":
        shared, singletons = legacy_group_issues(issue_items)
        issue_clusters = []
    else:
        issue_clusters = cluster_issues(issue_items)
        shared = [cluster.representative for cluster in issue_clusters if cluster.shared]
        singletons = [cluster.representative for cluster in issue_clusters if not cluster.shared]
```

5. Pass `issue_clusters=issue_clusters` to `ReconciledVerdict(...)`.
6. Delete the old private issue-matching helpers from `reconcile.py` after focused tests pass.

- [ ] **Step 4: Run focused reconciliation tests**

Run:

```bash
python -m pytest tests/test_reconcile.py tests/test_issue_matching.py -q
```

Expected: all focused tests pass.

- [ ] **Step 5: Run full tests**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/krystal_quorum/reconcile.py tests/test_reconcile.py
git commit -m "feat: use edge-based consensus matching"
```

### Task 4: Persist Cluster Edges

**Files:**

- Modify: `src/krystal_quorum/persist.py`
- Modify: `tests/test_persist.py`

- [ ] **Step 1: Add failing persistence test**

Add this test to `tests/test_persist.py`:

```python
from krystal_quorum.models import ReviewIssue


def test_persist_run_writes_issue_cluster_edges_to_json_and_summary(tmp_path: Path):
    plan_text = "## Rollback\n- Missing"
    issue_a = ReviewIssue(id="B1", section="Plan", claim="No rollback plan is described.", evidence="")
    issue_b = ReviewIssue(id="B2", section="Plan", claim="Missing backout path if deployment fails.", evidence="")
    result = reconcile(
        plan_path="plan.md",
        plan_text=plan_text,
        reviewers_used=["agy", "claude"],
        round1_outputs=[
            ReviewerOutput(
                reviewer="agy",
                round=1,
                verdict=Verdict.REVISE,
                confidence=0.8,
                blocking_issues=[issue_a],
                suggestions=[],
                per_clause={"rollback.plan": ClauseStatus.UNSATISFIED},
                raw_response="{}",
                elapsed_seconds=0.1,
            ),
            ReviewerOutput(
                reviewer="claude",
                round=1,
                verdict=Verdict.REVISE,
                confidence=0.8,
                blocking_issues=[issue_b],
                suggestions=[],
                per_clause={"rollback.plan": ClauseStatus.UNSATISFIED},
                raw_response="{}",
                elapsed_seconds=0.1,
            ),
        ],
        round2_outputs=[],
    )

    run_dir = persist_run(tmp_path, Path("plan.md"), plan_text, result)
    reconciled = json.loads((run_dir / "reconciled.json").read_text(encoding="utf-8"))
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")

    assert reconciled["schema_version"] == "1.2"
    assert reconciled["issue_clusters"][0]["edges"][0]["match_reason"] == (
        "shared topic rollback with absence intent; gap overlap: recovery"
    )
    assert "## Issue Clusters" in summary
    assert "gap overlap: recovery" in summary
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_persist.py::test_persist_run_writes_issue_cluster_edges_to_json_and_summary -q
```

Expected: fails until `summary.md` renders issue clusters.

- [ ] **Step 3: Add cluster summary section**

Add this helper in `src/krystal_quorum/persist.py`:

```python
def _issue_cluster_lines(result: ReconciledVerdict) -> list[str]:
    lines = ["## Issue Clusters\n\n"]
    if not result.issue_clusters:
        lines.append("- None.\n\n")
        return lines
    for cluster in result.issue_clusters:
        status = "shared" if cluster.shared else "singleton"
        reviewers = ", ".join(cluster.reviewers)
        lines.append(
            f"- **{cluster.topic}** ({status}, reviewers: {reviewers}): "
            f"{cluster.match_reason}\n"
        )
        for edge in cluster.edges:
            lines.append(
                f"  Edge: `{edge.left_reviewer}:{edge.left_issue_id}` <-> "
                f"`{edge.right_reviewer}:{edge.right_issue_id}` - {edge.match_reason}\n"
            )
        lines.append(f"  Representative: {cluster.representative.claim}\n")
    lines.append("\n")
    return lines
```

Call it in `build_summary` after singleton blockers:

```python
    lines.extend(_issue_cluster_lines(result))
```

- [ ] **Step 4: Run persistence tests**

Run:

```bash
python -m pytest tests/test_persist.py -q
```

Expected: all persistence tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/krystal_quorum/persist.py tests/test_persist.py
git commit -m "feat: persist consensus match edges"
```

### Task 5: Documentation And Final Verification

**Files:**

- Modify: `README.md`
- Modify: `docs/v0.4-experiment-report.md`

- [ ] **Step 1: Update README**

Add under `## Reconciliation Model`:

```markdown
Consensus matching is deterministic and explainable. Quorum groups reviewer
findings with a small public concept matcher for common review areas such as
acceptance criteria, rollback, tests, security, dependencies, and observability.
It does not use embeddings or hidden model calls to decide whether two issues
match. Persisted review artifacts include `issue_clusters` with members, direct
match edges, and match reasons.

Set `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy` to temporarily restore the older
token-overlap grouping behavior.
```

- [ ] **Step 2: Update experiment report**

In `docs/v0.4-experiment-report.md`, mark consensus matching as promoted only after the implementation passes this plan.

- [ ] **Step 3: Run final verification**

Run:

```bash
python -m pytest -q
python -m ruff check .
```

Expected:

```text
all tests pass
All checks passed!
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/v0.4-experiment-report.md
git commit -m "docs: explain edge-based consensus matching"
```

### Task 6: Server Review Before Implementation Or Merge

**Files:**

- No local code files modified in this task.

- [ ] **Step 1: Copy V4 plan to Gex**

Run:

```bash
scp docs/superpowers/plans/2026-06-23-consensus-matching-v4.md \
  gex44:/root/krystal-quorum/data/spec_reviews/2026-06-23-consensus-matching-v4.md
```

- [ ] **Step 2: Run the same five-reviewer quorum**

Run on Gex:

```bash
set -a
. /root/krystal-unity-core/.env
set +a
export OPENAI_BASE_URL="$OLLAMA_CLOUD_BASE_URL"
export OPENAI_API_KEY="$OLLAMA_CLOUD_API_KEY"
cd /root/krystal-quorum
uv run krystal-quorum review \
  /root/krystal-quorum/data/spec_reviews/2026-06-23-consensus-matching-v4.md \
  --config /root/krystal-quorum/data/spec_reviews/consensus-reviewers.toml \
  --reviewers openai:glm-5.2:cloud,openai:deepseek-v4-pro:cloud,command:grok,command:agy,command:claude \
  --out-dir /root/krystal-quorum/data/spec_reviews/quorum-runs \
  --round2
```

Expected: no `BLOCK` verdict. If the V4 plan blocks, update the design before implementing.
