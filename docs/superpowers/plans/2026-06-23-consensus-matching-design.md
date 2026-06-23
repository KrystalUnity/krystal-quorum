# Consensus Matching Design Review Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Krystal Quorum's issue consensus matching so differently worded reviewer findings can be promoted to shared blockers without merging unrelated issues.

**Architecture:** Add deterministic issue clustering with explainable concept matching before any semantic/embedding work. Preserve the existing safety-biased reconciliation model: uncertain matches stay singleton, and only findings from distinct reviewers can become shared blockers.

**Tech Stack:** Python 3.11+, Pydantic, pytest, existing `krystal_quorum.reconcile` flow.

---

## Current Behavior

Krystal Quorum currently groups blocking issues in `src/krystal_quorum/reconcile.py` using:

- an exact-ish claim fingerprint
- token overlap across `section + claim`

This is already better than exact text matching, but it remains brittle. Two reviewers may genuinely agree while using different language:

- "No rollback plan is described."
- "Missing backout path if deployment fails."

The current matcher can also become hard to explain if we keep adding ad hoc token rules inside reconciliation.

## Proposed v0.4 Scope

Create a deterministic, public-repo-safe consensus matcher. Do not use embeddings, paid semantic calls, hidden model arbitration, or network services in v0.4.

The matcher should:

- group same-topic findings from distinct reviewers
- avoid grouping unrelated findings that merely share generic words
- expose a human-readable match reason in artifacts
- keep uncertain matches as singleton blockers
- avoid promoting duplicate findings from the same reviewer into "shared"
- remain deterministic in CI

## Proposed Files

- Create: `src/krystal_quorum/issue_matching.py`
  - Owns tokenization, concept aliasing, pairwise issue match decisions, and issue cluster construction.
- Modify: `src/krystal_quorum/models.py`
  - Add optional artifact model(s), likely `IssueCluster` or `IssueMatchReason`, if we decide artifact explainability belongs in the public schema.
- Modify: `src/krystal_quorum/reconcile.py`
  - Replace private `_issues_match` / `_group_issues` internals with the new matcher while preserving current public outputs.
- Modify: `tests/test_reconcile.py`
  - Keep existing reconciliation tests green and add behavior tests around shared vs singleton grouping.
- Create: `tests/test_issue_matching.py`
  - Focused tests for tokenization, aliases, reviewer-distinct grouping, explainability, and false-positive guardrails.
- Modify: `README.md`
  - Document that consensus matching is deterministic and explainable, not majority voting and not semantic embedding.

## Matcher Design

### Concept Aliases

Use a small explicit alias table for common review topics:

```python
CONCEPT_ALIASES = {
    "acceptance": {
        "acceptance", "criteria", "done", "pass", "fail", "requirement",
    },
    "rollback": {
        "rollback", "backout", "back-out", "revert", "undo", "restore",
        "fallback", "feature-flag",
    },
    "tests": {
        "test", "tests", "pytest", "verification", "verify", "ci", "smoke",
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

The alias table is intentionally small. It should improve the most common plan-review domains without pretending to understand arbitrary language.

### Pairwise Match Rule

Two issues should match only when all of these are true:

1. They come from different reviewers.
2. They resolve to the same non-`general` concept.
3. They share either:
   - the canonical concept token plus at least one meaningful supporting token, or
   - a high normalized token overlap after alias canonicalization.
4. They do not trip an explicit negative guardrail.

Example positive:

- `rollback` + `deployment`
- `rollback` + `failure`

Example negative:

- "No rollback plan" and "No pytest command" both contain "No", "plan", or "missing", but they have different concepts and should not group.

### Cluster Output

Internally, produce clusters like:

```python
IssueCluster(
    topic="rollback",
    reviewers=("agy", "claude"),
    representative_issue=<ReviewIssue>,
    issues=(...),
    match_reason="shared concept rollback; supporting overlap: deployment, failure",
)
```

Question for reviewers: should this cluster model be persisted in `reconciled.json` for explainability, or should v0.4 keep the existing `shared_blocking_issues` / `singleton_blocking_issues` fields and only add match reasons to `summary.md`?

## False Positive Guardrails

Do not group:

- issues from the same reviewer only
- findings with no recognized concept unless exact/fingerprint match already succeeds
- findings whose only overlap is stopwords or generic review terms like `missing`, `plan`, `issue`, `risk`
- different concepts even if both are in the same section

## Tests To Write First

### Task 1: Issue Matcher Unit Tests

**Files:**

- Create: `tests/test_issue_matching.py`
- Create: `src/krystal_quorum/issue_matching.py`

- [ ] **Step 1: Write failing tests**

```python
from krystal_quorum.issue_matching import group_issue_clusters
from krystal_quorum.models import ReviewIssue


def issue(id: str, claim: str, section: str = "Plan") -> ReviewIssue:
    return ReviewIssue(id=id, section=section, claim=claim, evidence="evidence")


def test_groups_rollback_and_backout_from_distinct_reviewers():
    clusters = group_issue_clusters(
        [
            ("agy", issue("B1", "No rollback plan is described.")),
            ("claude", issue("B2", "Missing backout path if deployment fails.")),
        ]
    )

    shared = [cluster for cluster in clusters if cluster.shared]

    assert len(shared) == 1
    assert shared[0].topic == "rollback"
    assert shared[0].reviewers == ("agy", "claude")
    assert "rollback" in shared[0].match_reason


def test_keeps_rollback_and_tests_separate():
    clusters = group_issue_clusters(
        [
            ("agy", issue("B1", "No rollback plan is described.")),
            ("grok", issue("B2", "The pytest verification command is missing.", "Tests")),
        ]
    )

    assert all(not cluster.shared for cluster in clusters)
    assert {cluster.topic for cluster in clusters} == {"rollback", "tests"}


def test_same_reviewer_duplicates_do_not_create_shared_cluster():
    clusters = group_issue_clusters(
        [
            ("agy", issue("B1", "No rollback plan is described.")),
            ("agy", issue("B2", "Missing backout path if deployment fails.")),
        ]
    )

    assert all(not cluster.shared for cluster in clusters)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_issue_matching.py -q
```

Expected: import failure or assertion failures because the matcher does not exist yet.

- [ ] **Step 3: Implement minimal matcher**

Implement deterministic tokenization, alias canonicalization, topic selection, and cluster grouping.

- [ ] **Step 4: Verify focused tests pass**

Run:

```bash
python -m pytest tests/test_issue_matching.py -q
```

Expected: all focused issue-matching tests pass.

### Task 2: Reconciliation Integration Tests

**Files:**

- Modify: `tests/test_reconcile.py`
- Modify: `src/krystal_quorum/reconcile.py`

- [ ] **Step 1: Add failing reconciliation tests**

Add a test proving that paraphrased rollback/backout findings from distinct reviewers are promoted to one shared blocker.

Add another test proving that unrelated concepts remain singleton blockers.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_reconcile.py -q
```

Expected: at least the new rollback/backout integration test fails under the current matcher.

- [ ] **Step 3: Integrate matcher into reconciliation**

Replace the private grouping helpers in `reconcile.py` with `issue_matching.group_issue_clusters(...)`. Preserve existing `shared_blocking_issues` and `singleton_blocking_issues` behavior.

- [ ] **Step 4: Verify reconciliation tests pass**

Run:

```bash
python -m pytest tests/test_reconcile.py tests/test_issue_matching.py -q
```

Expected: all focused tests pass.

### Task 3: Artifact Explainability Decision

**Files:**

- Modify: `src/krystal_quorum/models.py`
- Modify: `src/krystal_quorum/persist.py`
- Modify: `tests/test_persist.py`
- Modify: `README.md`

- [ ] **Step 1: Decide artifact shape**

Preferred minimal shape:

```json
{
  "issue_clusters": [
    {
      "topic": "rollback",
      "reviewers": ["agy", "claude"],
      "issue_ids": ["B1", "B2"],
      "shared": true,
      "match_reason": "shared concept rollback; supporting overlap: deployment, failure"
    }
  ]
}
```

Alternative minimal path: leave `reconciled.json` schema unchanged and show match reasons only in `summary.md`.

- [ ] **Step 2: Write artifact test**

Test that the match reason is visible wherever we choose to expose it.

- [ ] **Step 3: Implement and document**

Update docs so users know Quorum is using deterministic concept matching, not hidden LLM agreement scoring.

## Review Questions For Agents

Please review this design before implementation.

Focus on:

1. False positives: where would this incorrectly merge unrelated findings?
2. False negatives: where would it still miss obvious agreement?
3. Explainability: should match reasons be persisted in `reconciled.json`, `summary.md`, or both?
4. Schema risk: is adding `issue_clusters` worth a schema version bump?
5. Public-repo safety: does this reveal any proprietary Krystal-specific method, or is it safely generic?
6. Implementation order: should we land matcher-only first, then artifact explainability, or combine them?

## Non-Goals

- No embeddings in v0.4.
- No paid model call to adjudicate issue similarity.
- No majority-rule voting change.
- No removal of single-reviewer fail-closed behavior.
- No broad review rubric implementation in the same PR.
