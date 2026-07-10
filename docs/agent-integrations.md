# Agent Integrations

Krystal Quorum is a two-gate, multi-AI review workflow for coding agents. It
does not replace Claude Code, Hermes, OpenClaw, Codex, GitHub Copilot, or local
agent runners. It reviews a commitment-bearing markdown plan before edits, then
reviews the implementation diff against the approved plan after normal tests.
Installed skills automate this policy; the GitHub Action is the hard CI
enforcement layer.

## Install

Install from PyPI:

```bash
python -m pip install krystal-quorum
```

For development from the checkout:

```bash
python -m pip install -e ".[dev]"
```

Smoke test:

```bash
krystal-quorum demo
```

Install project-local agent integration files:

```bash
krystal-quorum init --list-targets
krystal-quorum init --target claude-code
krystal-quorum init --target codex
krystal-quorum init --target copilot
krystal-quorum init --target hermes
krystal-quorum init --target claw
krystal-quorum init --target openclaw
krystal-quorum init --target opencode
krystal-quorum init --target all
```

## Two-Gate Workflow

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

Quorum recognizes commitments in these sections. For non-trivial work, the
installed agent skill automatically follows this sequence:

1. Write or locate the plan and use the configured real reviewer profile.
   If no profile exists, ask the human once; `mock` is installation smoke-only.
2. Run `review --bind-repo .` before edits. On `APPROVE`, retain the emitted
   unsigned `approval.json`; on `REVISE` or `BLOCK`, revise and rerun or return
   the unresolved decision to the human.
3. Implement only the approved scope and run normal tests.
4. Run `diff --approval <approval.json>` with the same reviewer profile.
   Remediate a `REVISE` or `BLOCK`, or present human triage, then report both
   gate verdicts and artifact paths.

Do not automatically commit, push, or deploy. Reviewer artifacts can contain
plans, patches, prompts, and findings, so keep them out of source control and
choose explicitly before exposing secret-looking or untracked input.

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
2. Invoke the skill or command. It automatically applies the shared two-gate
   workflow for non-trivial implementation:

```bash
krystal-quorum review docs/plans/<change>.md --bind-repo . --reviewers <real-reviewers>
```

3. Keep the approval receipt, run normal tests, and run verified `diff` review.
4. Continue only after handling `REVISE` or `BLOCK` findings.

## Use Quorum With Codex

Project-level Codex-style skill install:

```bash
krystal-quorum init --target codex
```

The command installs:

```bash
.codex/skills/krystal-quorum-review/SKILL.md
.krystal-quorum/agents/quorum-review.md
```

Ask Codex to run the skill before implementing a substantial plan. The shared
workflow file under `.krystal-quorum/agents/` keeps the review gate consistent
with the other agent packs.

## Use Quorum With GitHub Copilot

GitHub Copilot project skills live under `.github/skills/<skill-name>/SKILL.md`.
Install the Copilot pack with:

```bash
krystal-quorum init --target copilot
```

It installs `.github/skills/krystal-quorum-review/SKILL.md` without pre-approved
shell tools. The skill automatically delegates non-trivial work to the shared
two-gate workflow while retaining human control.

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

`claw` is an alias for the same pack:

```bash
krystal-quorum init --target claw
```

Use Quorum before dispatching implementation agents. Attach the Quorum artifact
path to any downstream worker so it can see what was approved, revised, or
blocked.

## Use Quorum With OpenCode

Install the OpenCode-compatible instruction:

```bash
krystal-quorum init --target opencode
```

The command installs:

```bash
.opencode/skills/krystal-quorum-review.md
.krystal-quorum/agents/quorum-review.md
```

Use the instruction to invoke the shared two-gate workflow for non-trivial
implementation work.

## Use Quorum Inside CI

The repository includes a GitHub Action for hard, standalone implementation
diff enforcement. Use the root action from a pinned release with exact
pull-request SHAs. It does not accept a local approval receipt and therefore
reports `unverified_reference` provenance by design:

```yaml
name: Review implementation evidence

on:
  pull_request:
jobs:
  quorum:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - id: quorum
        uses: KrystalUnity/krystal-quorum@v0.7.0
        with:
          mode: diff
          plan: docs/plans/change.md
          base: ${{ github.event.pull_request.base.sha }}
          head: ${{ github.event.pull_request.head.sha }}
          reviewers: openai:gpt-4.1,openai:o4-mini
          include-untracked: "false"
          package-spec: krystal-quorum==0.7.0
      - name: Upload Quorum artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: quorum-review
          path: ${{ steps.quorum.outputs.output-dir }}
```

The Action is intentionally independent of agent skills and can fail even when
an agent did not run its local two-gate policy. Keep upload artifacts private:
they can contain reviewed plan and patch content. Hosted diff review is excluded
from v0.7.

For a local command, Ollama, or API-backed plan review, configure the reviewer
profile used by the installed agent skill. For a standalone API-backed Action
review, pass credentials as environment secrets:

```yaml
- uses: KrystalUnity/krystal-quorum@v0.7.0
  with:
    plan: docs/plans/change.md
    reviewers: openai:gpt-4.1,openai:o4-mini
    round2: "true"
    require-diversity: "true"
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

Hosted Quorum packs remain available for plan-only review and are secondary to
the local and standalone CI paths above. Create a `KU_TOKEN` repository secret
only when intentionally selecting a hosted plan-review pack:

```yaml
- uses: KrystalUnity/krystal-quorum@v0.7.0
  with:
    plan: docs/plans/change.md
    reviewers: hosted:quick
    api-token: ${{ secrets.KU_TOKEN }}
```

For reproducible CI, pin the installed Python package as well as the action
tag:

```yaml
- uses: KrystalUnity/krystal-quorum@v0.7.0
  with:
    plan: docs/plans/change.md
    reviewers: mock
    package-spec: krystal-quorum==0.7.0
```

`mock` is a no-secret structural smoke test only. It is useful for confirming
the workflow is wired, but it is not a multi-AI review.

The Action sets `output-dir` and `latest-output-dir` before returning the
Quorum exit code, so `if: always()` follow-up steps can upload artifacts or
post findings even when a `REVISE` or `BLOCK` verdict fails the check.

When testing changes from this repository checkout, use the development wrapper
at `integrations/github-action` and set `package-spec: "."`.

## Reviewer Templates

Templates live under `integrations/agent-templates/`:

- `ollama.toml`: local Ollama command examples.
- `openai-compatible.toml`: OpenAI or compatible endpoint examples.
- `local-command-reviewers.toml`: placeholder command reviewers for local
  Claude, Codex, Antigravity, Grok, or other wrappers.

The command-reviewer template intentionally contains placeholder script paths.
It does not include private Krystal Unity server paths, credentials, or wrappers.

