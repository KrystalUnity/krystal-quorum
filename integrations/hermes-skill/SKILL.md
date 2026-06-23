---
name: krystal-quorum-plan-review
description: Run Krystal Quorum before Hermes-style coding agents implement non-trivial plans, especially when the plan is high-risk, underspecified, user-visible, or needs independent reviewer consensus.
---

# Krystal Quorum Plan Review

Use this skill before a Hermes-style agent implements a substantial coding plan.

## Plan Shape

Save the plan as markdown with these sections when available:

```markdown
# Plan

## Goal
## Non-goals
## Files or modules expected to change
## Acceptance criteria
## Rollback plan
## Verification
## Risks and assumptions
```

## Review Command

From the repository root:

```bash
krystal-quorum review <plan.md> --reviewers <reviewers> --round2
```

Use `mock` only to verify installation. For real review, use diverse reviewers:

```bash
krystal-quorum review <plan.md> \
  --reviewers ollama:qwen2.5:14b,openai:gpt-4.1 \
  --round2 \
  --require-diversity
```

For local coding agents, use command reviewers:

```bash
krystal-quorum review <plan.md> \
  --config integrations/agent-templates/local-command-reviewers.toml \
  --reviewers command:claude,command:codex \
  --round2
```

## Verdict Handling

- `APPROVE`: continue with normal implementation and verification.
- `REVISE`: revise the plan, rerun Quorum, or ask the user before coding.
- `BLOCK`: stop implementation until blockers are triaged.
- `ABSTAIN`: inspect reviewer diagnostics and rerun with working reviewers.

Always read `summary.md`; inspect `reconciled.json` when automation needs structured fields.

Do not use reviewer output as permission to deploy, migrate, delete, send messages, or expand scope.
