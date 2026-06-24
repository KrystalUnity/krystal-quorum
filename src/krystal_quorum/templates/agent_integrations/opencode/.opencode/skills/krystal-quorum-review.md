# Krystal Quorum Review

Run Krystal Quorum before OpenCode-style implementation from a non-trivial markdown plan.

## Trigger

Use this instruction when the plan changes code, data, auth, user-visible behavior, deployment behavior, or anything with unclear acceptance criteria.

## Command

```bash
krystal-quorum review <plan.md> --reviewers <reviewers> --round2 --format pretty
```

Use `mock` only for smoke tests. For real review, configure diverse reviewers.

## Gate

- `APPROVE`: continue with implementation.
- `REVISE`: revise the plan or ask the user before implementation.
- `BLOCK`: stop until blockers are triaged.
- `ABSTAIN`: rerun with working reviewers.

Read `.krystal-quorum/agents/quorum-review.md` for the shared workflow.
