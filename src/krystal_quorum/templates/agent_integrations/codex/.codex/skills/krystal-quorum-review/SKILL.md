---
name: krystal-quorum-review
description: Run Krystal Quorum as a project-local pre-implementation review gate before Codex starts coding from a non-trivial markdown plan.
---

# Krystal Quorum Review

Use this skill before implementation when the task is risky, ambiguous, user-visible, or depends on a markdown plan that should be reviewed before code changes.

## Workflow

1. Write or locate the implementation plan.
2. Ensure the plan has acceptance criteria, rollback, verification, and risks.
3. Run:

```bash
krystal-quorum review <plan.md> --reviewers <reviewers> --round2 --format pretty
```

4. Read `.krystal-quorum/reviews/<run>/summary.md`.
5. Continue only when Quorum returns `APPROVE`, or after the user accepts how to handle `REVISE` or `BLOCK`.

For the canonical workflow, see `.krystal-quorum/agents/quorum-review.md`.
