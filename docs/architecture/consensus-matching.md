# ADR: Deterministic Consensus Matching

## Status

Accepted for v0.4 and carried forward in v0.5.

## Context

Krystal Quorum reconciles findings from multiple independent reviewers. Early matching relied on near-identical issue text, which made consensus brittle because different models describe the same risk in different words.

The tool needs matching that is:

- deterministic
- inspectable in persisted artifacts
- good enough for common plan-review risks
- independent of extra embedding or LLM calls

## Decision

Quorum groups reviewer issues with a deterministic public concept matcher. It recognizes common review topics such as acceptance criteria, rollback, tests, security, dependencies, observability, and operational safety.

Consensus requires:

- at least two different reviewers
- shared topic support terms
- enough support overlap to avoid broad false positives
- stricter gap-term overlap for absence-style findings

Persisted artifacts include `issue_clusters` with cluster members, direct match edges, and match reasons so users can audit why a finding was promoted.

## Consequences

This keeps consensus explainable and cheap. It is intentionally less magical than semantic embeddings, but safer for a public CLI because users can inspect and challenge every match.

The matcher remains safety-biased: a singleton blocker can still force `REVISE`, while shared blockers are promoted as stronger evidence.

## Rollback

Set `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy` to restore the older token-overlap matcher while retaining the newer artifact schema.
