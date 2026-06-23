# Agent Integrations

Krystal Quorum is a pre-implementation review gate for AI coding agents. It does
not replace Claude Code, Hermes, OpenClaw, Codex, or local agent runners. It
reviews a markdown plan before those tools implement it.

## Install

From PyPI:

```bash
python -m pip install krystal-quorum
```

For development:

```bash
python -m pip install -e ".[dev]"
```

Smoke test:

```bash
# From a krystal-quorum checkout:
krystal-quorum review examples/bad-plan.md --reviewers mock
```

Install project-local agent integration files:

```bash
krystal-quorum init --target claude-code
krystal-quorum init --target hermes
krystal-quorum init --target openclaw
```

## Plan File Shape

Use a markdown plan with enough detail for independent review:

```markdown
# Plan

## Goal
## Non-goals
## Files or modules expected to change
## Implementation steps
## Acceptance criteria
## Rollback plan
## Verification
## Risks and assumptions
```

Quorum works with any markdown, but sparse plans produce better reviewer
findings than approvals.

## Verdict Handling

- `APPROVE`: proceed with normal implementation and verification.
- `REVISE`: revise the plan or ask the user before implementation.
- `BLOCK`: stop until blockers are triaged.
- `ABSTAIN`: inspect diagnostics and rerun with reviewers that can produce strict JSON.

Always inspect `summary.md`. Use `reconciled.json` for automation.

## Use Quorum With Claude Code

Claude Code supports skills under `.claude/skills/<skill-name>/SKILL.md`.
Existing `.claude/commands/*.md` slash command files also still work. See the
Claude Code skills documentation: <https://docs.anthropic.com/en/docs/claude-code/skills>.

Project-level skill install:

```bash
krystal-quorum init --target claude-code
```

The command installs both the skill and optional slash-command style file:

```bash
.claude/skills/krystal-quorum-review/SKILL.md
.claude/commands/quorum-review.md
```

Typical Claude Code workflow:

1. Ask Claude to draft or refine a plan in `docs/plans/<change>.md`.
2. Invoke the skill or command, or ask Claude to run:

```bash
krystal-quorum review docs/plans/<change>.md --reviewers mock
```

3. Replace `mock` with real reviewers before trusting the result.
4. Continue only after handling `REVISE` or `BLOCK` findings.

## Use Quorum With Hermes

Copy the Hermes skill into the location your Hermes-style runner uses for
Agent Skills or workflow prompts:

```bash
krystal-quorum init --target hermes
```

Recommended command:

```bash
krystal-quorum review docs/plans/change.md \
  --reviewers ollama:qwen2.5:14b,openai:gpt-4.1 \
  --round2 \
  --require-diversity
```

If Hermes uses installed local agents, use command reviewers:

```bash
krystal-quorum review docs/plans/change.md \
  --config integrations/agent-templates/local-command-reviewers.toml \
  --reviewers command:claude,command:codex \
  --round2
```

## Use Quorum With OpenClaw

Copy the OpenClaw skill into the skill or prompt directory used by your
OpenClaw-style coordinator:

```bash
krystal-quorum init --target openclaw
```

Use Quorum before dispatching implementation agents. Attach the Quorum artifact
path to any downstream worker so it can see what was approved, revised, or
blocked.

## Use Quorum Inside CI

The repository includes a composite GitHub Action at
`integrations/github-action`.

```yaml
name: Review plan

on:
  pull_request:
    paths:
      - "docs/plans/**.md"

jobs:
  quorum:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./integrations/github-action
        with:
          plan: docs/plans/change.md
          reviewers: mock
```

For real API-backed reviewers:

```yaml
- uses: ./integrations/github-action
  with:
    plan: docs/plans/change.md
    reviewers: openai:gpt-4.1,openai:o4-mini
    round2: "true"
    require-diversity: "true"
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

When using the action outside this repository, set `package-spec` to a pinned
published package once releases are available.

## Reviewer Templates

Templates live under `integrations/agent-templates/`:

- `ollama.toml`: local Ollama command examples.
- `openai-compatible.toml`: OpenAI or compatible endpoint examples.
- `local-command-reviewers.toml`: placeholder command reviewers for local
  Claude, Codex, Antigravity, Grok, or other wrappers.

The command-reviewer template intentionally contains placeholder script paths.
It does not include private Krystal Unity server paths, credentials, or wrappers.
