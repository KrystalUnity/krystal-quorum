# Agent Import Packs

Krystal Quorum ships project-local import packs for common AI coding agent workflows. Each pack installs a thin wrapper plus a shared Quorum review gate reference.

## Supported Targets

```bash
krystal-quorum init --list-targets
```

Targets:

- `claude-code`: Claude Code skill plus optional slash command.
- `codex`: project-local Codex-style skill.
- `hermes`: Hermes-style plan review skill.
- `claw`: alias for the OpenClaw-compatible pack.
- `openclaw`: OpenClaw-style pre-dispatch review skill.
- `opencode`: OpenCode-compatible instruction.
- `all`: install every canonical pack.

## Install

Install a single pack:

```bash
krystal-quorum init --target codex
```

Install every pack:

```bash
krystal-quorum init --target all
```

Use `--path <dir>` to install into another project and `--force` to overwrite generated files.

## Shared Workflow

Every target installs:

```text
.krystal-quorum/agents/quorum-review.md
```

That file defines the common review gate:

1. Write or locate the markdown plan.
2. Check that the plan includes goal, scope, acceptance criteria, rollback, verification, and risk notes.
3. Run `krystal-quorum review <plan.md> --reviewers <reviewers> --round2 --format pretty`.
4. Read the generated `summary.md`.
5. Proceed only after handling `REVISE`, `BLOCK`, or collapsed quorum findings.

The target-specific files adapt that same workflow to each agent's expected import shape.

## Output Shape

Use pretty output for human and agent transcripts:

```bash
krystal-quorum review docs/plans/change.md --reviewers mock --format pretty
```

Use JSON for automation:

```bash
krystal-quorum review docs/plans/change.md --reviewers mock --format json
```

JSON is the default to preserve scripting compatibility.
