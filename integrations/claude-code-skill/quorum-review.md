---
name: quorum-review
description: Review a markdown implementation plan with Krystal Quorum before coding.
argument-hint: <plan.md> [reviewers]
---

Run Krystal Quorum against the markdown plan named in the first argument.

Treat the first argument as the plan path. Treat the optional second argument as
the comma-separated reviewer list. If no reviewer list is supplied, use `mock`
only as a smoke test and tell the user they should configure real reviewers for
meaningful review.

Steps:

1. Confirm the plan file exists.
2. Run the review:

```bash
krystal-quorum review <plan.md> --reviewers <reviewers> --round2
```

3. If the project has a Quorum config, include `--config <path>`.
4. Open the generated `summary.md`.
5. Report the verdict, shared blockers, singleton blockers, contradictions, and artifact path.
6. Do not implement code after `REVISE` or `BLOCK` unless the user explicitly chooses the next action.

Install option for Claude Code command users:

```bash
mkdir -p .claude/commands
cp integrations/claude-code-skill/quorum-review.md .claude/commands/quorum-review.md
```
