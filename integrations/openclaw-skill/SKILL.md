---
name: krystal-quorum-openclaw-review
description: Add a Krystal Quorum pre-dispatch review gate to OpenClaw-style agent workflows before implementation, tool execution, or multi-agent handoff of risky markdown coding plans.
---

# Krystal Quorum OpenClaw Review

Use this as a pre-dispatch gate before an OpenClaw-style coordinator assigns implementation work.

## Plan Shape

Require a markdown plan with:

- goal and scope
- non-goals
- implementation steps
- acceptance criteria
- rollback plan
- verification commands
- security, data, or operational risks

## Review Gate

Run Quorum before dispatch:

```bash
krystal-quorum review <plan.md> --reviewers <configured-reviewers> --round2
```

Recommended local-agent shape:

```bash
krystal-quorum review <plan.md> \
  --config integrations/agent-templates/local-command-reviewers.toml \
  --reviewers command:claude,command:codex,command:agy \
  --round2 \
  --require-diversity
```

## Verdict Handling

- `APPROVE`: dispatch implementation with the reviewed plan attached.
- `REVISE`: return the plan to the planner with the Quorum summary.
- `BLOCK`: do not dispatch implementation; ask for human triage.
- `ABSTAIN`: treat as inconclusive if too few reviewers produced usable output.

Inspect `summary.md` for human-readable triage and `reconciled.json` for automation.

Krystal Quorum is a review step. It is not an agent runtime and does not run tools.
