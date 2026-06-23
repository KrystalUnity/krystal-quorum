---
name: krystal-quorum-review
description: Run Krystal Quorum as a pre-implementation review gate in Claude Code when a coding task has a markdown plan, touches risky behavior, lacks acceptance criteria, or needs multi-reviewer scrutiny before edits.
---

# Krystal Quorum Review

Use this skill before implementation when the task is non-trivial, risky, ambiguous, or user-visible.

## Workflow

1. Write the intended implementation plan to a markdown file, usually under `docs/plans/` or `.krystal-quorum/plans/`.
2. Make the plan concrete enough for external review:
   - goal and non-goals
   - files or modules expected to change
   - acceptance criteria
   - rollback plan
   - verification commands
   - safety assumptions or known risks
3. Run Quorum from the repository root:

```bash
krystal-quorum review <plan.md> --reviewers <reviewers> --round2
```

4. Read the generated `summary.md` and `reconciled.json` under `.krystal-quorum/reviews/` or the configured output directory.
5. Treat the verdict as a review signal:
   - `APPROVE`: proceed, but still implement and verify normally.
   - `REVISE`: revise the plan or ask the user before coding.
   - `BLOCK`: do not implement until blockers are triaged.
   - `ABSTAIN`: inspect reviewer diagnostics and rerun with usable reviewers.
6. Do not use reviewer output as permission to deploy, delete data, send external messages, broaden scope, or bypass user approval.

## Reviewer Defaults

Use `mock` only for smoke tests. For real review, prefer at least two diverse reviewers:

```bash
krystal-quorum review docs/plans/change.md \
  --reviewers ollama:qwen2.5:14b,openai:gpt-4.1 \
  --round2 \
  --require-diversity
```

For installed local coding agents, use command reviewers:

```bash
krystal-quorum review docs/plans/change.md \
  --config integrations/agent-templates/local-command-reviewers.toml \
  --reviewers command:claude,command:codex \
  --round2
```

If Quorum returns `REVISE` or `BLOCK`, summarize the blockers to the user and ask whether to revise the plan, rerun review, or stop.
