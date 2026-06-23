# Consensus Matching V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote genuinely matching reviewer findings into shared blockers using a deterministic, explainable matcher with a rollback switch and persisted match reasons.

**Architecture:** Add a focused `issue_matching.py` module that owns tokenization, concept selection, pairwise decisions, and cluster construction. Reconciliation consumes those clusters, persists them in schema `1.2`, and can fall back to legacy grouping with `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy`.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, existing Krystal Quorum CLI and reconciliation flow.

---

## V2 Decisions From Quorum Review

The first design review returned `BLOCK`. V2 resolves each blocker with an explicit decision:

- Exact threshold: use overlap coefficient `len(shared_support_terms) / min(len(left_support_terms), len(right_support_terms))`, with cutoff `0.50` and at least `1` shared supporting term.
- Exact fallback: unrecognized or tied topics resolve to `general`; `general` issues only match on exact fingerprint, never on concept overlap.
- Artifact schema: add `issue_clusters` to `reconciled.json` and show match reasons in `summary.md`.
- Schema version: bump reconciliation schema from `1.1` to `1.2`.
- Rollback: support `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy` to use the old grouping logic while keeping schema `1.2` with an empty `issue_clusters` list.
- Acceptance: add boundary tests for positive matches, negative matches, same-reviewer duplicates, `general` fallback, threshold behavior, artifact output, and rollback mode.

## File Map

- Create: `src/krystal_quorum/issue_matching.py`
  - Deterministic matcher implementation.
  - Exports `IssueMatchInput`, `cluster_issues`, `legacy_group_issues`.
- Modify: `src/krystal_quorum/models.py`
  - Add `IssueClusterMember` and `IssueCluster`.
  - Add `issue_clusters: list[IssueCluster]` to `ReconciledVerdict`.
- Modify: `src/krystal_quorum/reconcile.py`
  - Bump `SCHEMA_VERSION` to `1.2`.
  - Use deterministic matcher by default.
  - Use legacy matcher when `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy`.
- Modify: `src/krystal_quorum/persist.py`
  - Add an `Issue Clusters` section to `summary.md`.
- Create: `tests/test_issue_matching.py`
  - Unit and boundary tests for deterministic matching.
- Modify: `tests/test_reconcile.py`
  - Integration tests for shared blockers and rollback mode.
- Modify: `tests/test_persist.py`
  - Artifact and summary explainability tests.
- Modify: `README.md`
  - Document deterministic consensus matching and rollback mode.
- Modify: `docs/v0.4-experiment-report.md`
  - Mark consensus matching as promoted after implementation passes review.

## Exact Matching Contract

### Tokenization

Use this deterministic flow:

1. Lowercase text.
2. Replace `back-out` and `back out` with `backout`.
3. Replace `feature flag` and `feature-flag` with `featureflag`.
4. Extract tokens with `re.findall(r"[a-z0-9]+", text)`.
5. Canonicalize aliases to one topic token.
6. Drop tokens of length `<= 2`.

### Topic Selection

Topic candidates are:

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

Scoring:

- Section alias hit: `+2`
- Claim alias hit: `+1`
- Evidence alias hit: `+1`
- If the highest score is `0`, topic is `general`.
- If two or more topics tie for the highest score, topic is `general`.

This makes ambiguous findings conservative. They stay singleton unless exact fingerprint matching catches them.

### Pairwise Match Rule

Two issues match when:

1. Reviewer IDs differ.
2. Exact fingerprint matches, or the remaining deterministic rules match.
3. Both issues have the same topic.
4. Topic is not `general`.
5. One of these same-topic conditions is true:
   - both issues express absence for the same topic, using one of `no`, `missing`, `lacks`, `lack`, `omits`, `omitted`, `absent`, `without`;
   - at least `1` supporting term overlaps and the overlap coefficient is `>= 0.50`, excluding stopwords, generic review words, absence terms, and the topic token.

The first condition intentionally groups concise equivalent findings such as:

- "No rollback plan is described."
- "Missing backout path if deployment fails."

The second and third conditions cover richer claims where reviewers share meaningful context.

### Stopwords And Generic Review Terms

```python
STOPWORDS = {
    "a", "an", "and", "are", "as", "be", "but", "by", "for", "from",
    "has", "have", "if", "in", "into", "is", "it", "its", "of", "on",
    "or", "that", "the", "this", "to", "with",
}

GENERIC_REVIEW_TERMS = {
    "claim", "evidence", "finding", "findings", "gap", "gaps", "issue",
    "issues", "missing", "no", "not", "omits", "omitted", "plan", "risk",
    "review", "reviewer", "section", "unclear", "undefined", "without",
}

ABSENCE_TERMS = {
    "no", "missing", "lacks", "lack", "omits", "omitted", "absent", "without",
}
```

### Match Reasons

Every cluster gets one reason:

- `exact fingerprint match`
- `shared topic rollback with absence intent`
- `shared topic tests with overlap coefficient 0.50; supporting overlap: pytest, verification`
- `shared topic security with overlap coefficient 0.67; supporting overlap: admin, export`
- `singleton; no deterministic consensus match`

These reasons are persisted in `reconciled.json` and displayed in `summary.md`.

## Acceptance Criteria

Implementation is complete only when all of these are true:

- `python -m pytest tests/test_issue_matching.py -q` passes.
- `python -m pytest tests/test_reconcile.py tests/test_persist.py -q` passes.
- `python -m pytest -q` passes.
- `python -m ruff check .` passes.
- Rollback mode test proves `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy` keeps rollback/backout paraphrases as singleton blockers.
- Default mode test proves rollback/backout paraphrases from distinct reviewers become one shared blocker.
- Same-reviewer duplicates never create a shared blocker.
- `general` fallback issues never match unless exact fingerprint matches.
- Persisted `reconciled.json` includes `schema_version: "1.2"` and an `issue_clusters` array.
- `summary.md` includes an `Issue Clusters` section with match reasons.

## Rollback Plan

If deterministic matching regresses behavior after merge:

1. Set `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy` in the environment running Quorum.
2. Re-run the affected review command.
3. Confirm `issue_clusters` is empty and grouping behavior matches schema `1.1` legacy results.
4. If release rollback is needed, revert the commit that introduced `issue_matching.py` and schema `1.2`.

The runtime rollback switch is intentionally environment-only so GitHub Actions, local CLI users, and server command wrappers can disable the matcher without code changes.

---

### Task 1: Add Issue Cluster Models

**Files:**

- Modify: `src/krystal_quorum/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write the failing model test**

Add this test to `tests/test_models.py`:

```python
from krystal_quorum.models import IssueCluster, IssueClusterMember, ReviewIssue


def test_issue_cluster_accepts_explainable_payload():
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
        match_reason="shared topic rollback with absence intent",
    )

    assert cluster.topic == "rollback"
    assert cluster.reviewers == ["agy", "claude"]
    assert cluster.representative.id == "B1"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_models.py::test_issue_cluster_accepts_explainable_payload -q
```

Expected: fails with `ImportError` for `IssueCluster`.

- [ ] **Step 3: Add model classes**

Add these classes after `ContradictionFinding` in `src/krystal_quorum/models.py`:

```python
class IssueClusterMember(StrictModel):
    reviewer: str
    issue_id: str
    section: str
    claim: str


class IssueCluster(StrictModel):
    topic: str
    shared: bool
    reviewers: list[str]
    representative: ReviewIssue
    members: list[IssueClusterMember]
    match_reason: str
```

Add this field to `ReconciledVerdict` after `singleton_blocking_issues`:

```python
    issue_clusters: list[IssueCluster]
```

- [ ] **Step 4: Run model tests**

Run:

```bash
python -m pytest tests/test_models.py -q
```

Expected: the new model test passes. If existing tests fail because `ReconciledVerdict` construction is missing `issue_clusters`, continue to Task 3, update those constructors, and rerun.

- [ ] **Step 5: Commit**

Run after the relevant green point:

```bash
git add src/krystal_quorum/models.py tests/test_models.py
git commit -m "feat: add issue cluster artifact models"
```

### Task 2: Add Deterministic Issue Matcher

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


def test_groups_rollback_and_backout_from_distinct_reviewers():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "No rollback plan is described.")),
            ("claude", issue("B2", "Missing backout path if deployment fails.")),
        ]
    )

    shared = [cluster for cluster in clusters if cluster.shared]

    assert len(shared) == 1
    assert shared[0].topic == "rollback"
    assert shared[0].reviewers == ["agy", "claude"]
    assert shared[0].match_reason == "shared topic rollback with absence intent"


def test_keeps_rollback_and_tests_separate():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "No rollback plan is described.")),
            ("grok", issue("B2", "The pytest verification command is missing.", "Tests")),
        ]
    )

    assert all(not cluster.shared for cluster in clusters)
    assert {cluster.topic for cluster in clusters} == {"rollback", "tests"}


def test_same_reviewer_duplicates_do_not_create_shared_cluster():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "No rollback plan is described.")),
            ("agy", issue("B2", "Missing backout path if deployment fails.")),
        ]
    )

    assert all(not cluster.shared for cluster in clusters)


def test_general_fallback_does_not_match_without_exact_fingerprint():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "The story is vague.")),
            ("claude", issue("B2", "The description is ambiguous.")),
        ]
    )

    assert [cluster.topic for cluster in clusters] == ["general", "general"]
    assert all(not cluster.shared for cluster in clusters)


def test_exact_fingerprint_can_match_general_findings():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "The story is vague.")),
            ("claude", issue("B2", "The story is vague.")),
        ]
    )

    assert len([cluster for cluster in clusters if cluster.shared]) == 1
    assert clusters[0].topic == "general"
    assert clusters[0].match_reason == "exact fingerprint match"


def test_supporting_overlap_threshold_groups_richer_findings():
    clusters = cluster_issues(
        [
            ("glm", issue("B1", "Security permission checks for admin export are missing.")),
            ("claude", issue("B2", "Auth permission checks for admin export are undefined.")),
        ]
    )

    shared = [cluster for cluster in clusters if cluster.shared]

    assert len(shared) == 1
    assert shared[0].topic == "security"
    assert "overlap coefficient" in shared[0].match_reason
    assert "supporting overlap" in shared[0].match_reason


def test_ambiguous_tied_topic_becomes_general():
    clusters = cluster_issues(
        [
            ("agy", issue("B1", "Rollback security test is missing.")),
            ("claude", issue("B2", "Security rollback test is missing.")),
        ]
    )

    assert clusters[0].topic == "general"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_issue_matching.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'krystal_quorum.issue_matching'`.

- [ ] **Step 3: Create matcher module**

Create `src/krystal_quorum/issue_matching.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import re

from krystal_quorum.models import IssueCluster, IssueClusterMember, ReviewIssue

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
TOPIC_BY_ALIAS = {alias: topic for topic, aliases in TOPIC_ALIASES.items() for alias in aliases}
STOPWORDS = {
    "a", "an", "and", "are", "as", "be", "but", "by", "for", "from",
    "has", "have", "if", "in", "into", "is", "it", "its", "of", "on",
    "or", "that", "the", "this", "to", "with",
}
GENERIC_REVIEW_TERMS = {
    "claim", "evidence", "finding", "findings", "gap", "gaps", "issue",
    "issues", "missing", "no", "not", "omits", "omitted", "plan", "risk",
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
    source: IssueMatchInput
    topic: str
    all_terms: set[str]
    support_terms: set[str]
    absence_terms: set[str]
    fingerprint: str


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


def _canonical_tokens(text: str) -> set[str]:
    return {
        _canonical_token(token)
        for token in _raw_tokens(text)
        if len(token) > 2 or token in ABSENCE_TERMS
    }


def _score_topic(issue: ReviewIssue) -> str:
    scores = {topic: 0 for topic in TOPIC_ALIASES}
    for token in _raw_tokens(issue.section):
        topic = TOPIC_BY_ALIAS.get(token)
        if topic:
            scores[topic] += 2
    for token in _raw_tokens(issue.claim):
        topic = TOPIC_BY_ALIAS.get(token)
        if topic:
            scores[topic] += 1
    for token in _raw_tokens(issue.evidence):
        topic = TOPIC_BY_ALIAS.get(token)
        if topic:
            scores[topic] += 1
    highest = max(scores.values())
    if highest == 0:
        return "general"
    winners = [topic for topic, score in scores.items() if score == highest]
    return winners[0] if len(winners) == 1 else "general"


def _analyze(source: IssueMatchInput) -> _AnalyzedIssue:
    issue = source.issue
    text = f"{issue.section} {issue.claim} {issue.evidence}"
    topic = _score_topic(issue)
    all_terms = _canonical_tokens(text)
    support_terms = {
        term
        for term in all_terms
        if term not in STOPWORDS
        and term not in GENERIC_REVIEW_TERMS
        and term not in ABSENCE_TERMS
        and term != topic
    }
    absence_terms = {term for term in _raw_tokens(text) if term in ABSENCE_TERMS}
    return _AnalyzedIssue(
        source=source,
        topic=topic,
        all_terms=all_terms,
        support_terms=support_terms,
        absence_terms=absence_terms,
        fingerprint=_fingerprint(issue),
    )


def _match_reason(left: _AnalyzedIssue, right: _AnalyzedIssue) -> str | None:
    if left.source.reviewer == right.source.reviewer:
        return None
    if left.fingerprint == right.fingerprint:
        return "exact fingerprint match"
    if left.topic != right.topic or left.topic == "general":
        return None
    shared_support = sorted(left.support_terms & right.support_terms)
    if left.absence_terms and right.absence_terms:
        return f"shared topic {left.topic} with absence intent"
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


def _member(source: IssueMatchInput) -> IssueClusterMember:
    return IssueClusterMember(
        reviewer=source.reviewer,
        issue_id=source.issue.id,
        section=source.issue.section,
        claim=source.issue.claim,
    )


def _cluster_from_group(
    topic: str,
    sources: list[IssueMatchInput],
    match_reason: str,
) -> IssueCluster:
    reviewers = sorted({source.reviewer for source in sources})
    representative = sources[0].issue
    return IssueCluster(
        topic=topic,
        shared=len(reviewers) >= 2,
        reviewers=reviewers,
        representative=representative,
        members=[_member(source) for source in sources],
        match_reason=match_reason,
    )


def cluster_issues(items: list[tuple[str, ReviewIssue]]) -> list[IssueCluster]:
    analyzed = [_analyze(IssueMatchInput(reviewer, issue)) for reviewer, issue in items]
    groups: list[tuple[str, str, list[_AnalyzedIssue]]] = []
    for item in analyzed:
        for index, (topic, reason, group) in enumerate(groups):
            match = _match_reason(group[0], item)
            if match is not None:
                groups[index] = (topic, match if reason.startswith("singleton;") else reason, [*group, item])
                break
        else:
            groups.append(
                (
                    item.topic,
                    "singleton; no deterministic consensus match",
                    [item],
                )
            )
    return [
        _cluster_from_group(topic, [item.source for item in group], reason)
        for topic, reason, group in groups
    ]


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

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/krystal_quorum/issue_matching.py tests/test_issue_matching.py
git commit -m "feat: add deterministic issue matcher"
```

### Task 3: Integrate Matcher Into Reconciliation

**Files:**

- Modify: `src/krystal_quorum/reconcile.py`
- Modify: `tests/test_reconcile.py`

- [ ] **Step 1: Add failing reconciliation tests**

Add these tests to `tests/test_reconcile.py`:

```python
def test_reconcile_promotes_rollback_backout_consensus():
    issue_a = ReviewIssue(
        id="B1",
        section="Plan",
        claim="No rollback plan is described.",
        evidence="Rollback is not mentioned.",
    )
    issue_b = ReviewIssue(
        id="B2",
        section="Plan",
        claim="Missing backout path if deployment fails.",
        evidence="No deployment failure recovery path is listed.",
    )

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
    assert len(result.singleton_blocking_issues) == 0
    assert result.issue_clusters[0].match_reason == "shared topic rollback with absence intent"


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

Expected: fails because `schema_version` is still `1.1` and `issue_clusters` is not populated.

- [ ] **Step 3: Modify reconciliation**

In `src/krystal_quorum/reconcile.py`:

1. Add `import os`.
2. Import `cluster_issues` and `legacy_group_issues`.
3. Change `SCHEMA_VERSION = "1.2"`.
4. Replace `_group_issues(non_abstained)` usage with:

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

Leave the old private `_fingerprint`, `_issue_tokens`, `_issues_match`, and `_group_issues` in place only until all tests pass. After tests are green, delete those private helpers and the unused `re` import from `reconcile.py`.

- [ ] **Step 4: Run reconciliation tests**

Run:

```bash
python -m pytest tests/test_reconcile.py tests/test_issue_matching.py -q
```

Expected: all focused tests pass.

- [ ] **Step 5: Run full tests after model constructor updates**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass. If tests that construct `ReconciledVerdict` directly fail, add `issue_clusters=[]` to those constructors.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/krystal_quorum/reconcile.py tests/test_reconcile.py
git commit -m "feat: use deterministic issue clusters in reconciliation"
```

### Task 4: Persist Issue Cluster Explainability

**Files:**

- Modify: `src/krystal_quorum/persist.py`
- Modify: `tests/test_persist.py`

- [ ] **Step 1: Add failing persistence test**

Add this test to `tests/test_persist.py`:

```python
from krystal_quorum.models import ReviewIssue


def test_persist_run_writes_issue_clusters_to_json_and_summary(tmp_path: Path):
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
    assert reconciled["issue_clusters"][0]["match_reason"] == "shared topic rollback with absence intent"
    assert "## Issue Clusters" in summary
    assert "shared topic rollback with absence intent" in summary
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_persist.py::test_persist_run_writes_issue_clusters_to_json_and_summary -q
```

Expected: fails until `build_summary` renders issue clusters.

- [ ] **Step 3: Update summary builder**

Add this helper to `src/krystal_quorum/persist.py`:

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

Run:

```bash
git add src/krystal_quorum/persist.py tests/test_persist.py
git commit -m "feat: persist issue cluster explanations"
```

### Task 5: Documentation And Experiment Report

**Files:**

- Modify: `README.md`
- Modify: `docs/v0.4-experiment-report.md`

- [ ] **Step 1: Update README**

Add this paragraph under `## Reconciliation Model`:

```markdown
Consensus matching is deterministic and explainable. Quorum groups reviewer
findings with a small public concept matcher for common review areas such as
acceptance criteria, rollback, tests, security, dependencies, and observability.
It does not use embeddings or hidden model calls to decide whether two issues
match. Persisted review artifacts include `issue_clusters` with the reviewer
members and match reason.

Set `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy` to temporarily restore the older
token-overlap grouping behavior while keeping the schema-compatible artifact
shape.
```

- [ ] **Step 2: Update v0.4 experiment report**

In `docs/v0.4-experiment-report.md`, change the consensus matching candidate section to say:

```markdown
Product status: promoted into reconciliation behind a rollback switch. The
matcher is deterministic, persists `issue_clusters`, and can be disabled with
`KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy`.
```

- [ ] **Step 3: Run docs-adjacent checks**

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

Run:

```bash
git add README.md docs/v0.4-experiment-report.md
git commit -m "docs: explain deterministic consensus matching"
```

### Task 6: Final Verification And Server Review

**Files:**

- No code files modified in this task.

- [ ] **Step 1: Run final local verification**

Run:

```bash
python -m pytest -q
python -m ruff check .
git status --short --branch
```

Expected:

```text
all tests pass
All checks passed!
## experiment/v0.4-candidates...origin/experiment/v0.4-candidates
```

The status may show committed branch divergence until pushed.

- [ ] **Step 2: Push the branch**

Run:

```bash
git push
```

Expected: branch updates on `origin/experiment/v0.4-candidates`.

- [ ] **Step 3: Run Gex review before merge**

Copy this V2 plan to the server:

```bash
scp docs/superpowers/plans/2026-06-23-consensus-matching-v2.md \
  gex44:/root/krystal-quorum/data/spec_reviews/2026-06-23-consensus-matching-v2.md
```

Run the same reviewer set used for the V1 plan:

```bash
set -a
. /root/krystal-unity-core/.env
set +a
export OPENAI_BASE_URL="$OLLAMA_CLOUD_BASE_URL"
export OPENAI_API_KEY="$OLLAMA_CLOUD_API_KEY"
cd /root/krystal-quorum
uv run krystal-quorum review \
  /root/krystal-quorum/data/spec_reviews/2026-06-23-consensus-matching-v2.md \
  --config /root/krystal-quorum/data/spec_reviews/consensus-reviewers.toml \
  --reviewers openai:glm-5.2:cloud,openai:deepseek-v4-pro:cloud,command:grok,command:agy,command:claude \
  --out-dir /root/krystal-quorum/data/spec_reviews/quorum-runs \
  --round2
```

Expected: no `BLOCK` verdict. If the V2 plan still blocks, fix the design before implementing or merging.
