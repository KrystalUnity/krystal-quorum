# ADR: Local Command Reviewers

## Status

Accepted.

## Context

Many developers already use local coding agents, shell wrappers, or self-hosted model runners. Quorum should review plans with those tools without becoming an agent runtime or requiring every reviewer to be an HTTP API.

## Decision

Quorum supports `command:<name>` reviewers configured in TOML. A command reviewer receives the full review prompt on stdin and returns strict reviewer JSON on stdout. For wrappers that run detached agents, a reviewer can write JSON to `output_file`, and Quorum will wait for it for a bounded time.

Example:

```toml
[reviewers.local-codex]
type = "command"
command = ["codex", "exec", "--sandbox", "read-only", "--ephemeral", "-"]
timeout_s = 180
family = "codex"
```

Then:

```bash
krystal-quorum review docs/plans/change.md \
  --config krystal-quorum.toml \
  --reviewers command:local-codex \
  --round2
```

## Security Model

Command reviewers are opt-in. Quorum does not run shell commands by default, does not read API keys from files, and does not grant reviewer output authority to edit, deploy, or delete anything.

Users should treat configured commands as trusted local automation and prefer sandboxed/read-only agent modes where available.

## Consequences

This makes Quorum useful for local-agent teams without baking private wrappers into the public repo. It also keeps the public CLI neutral: Claude Code, Codex, Hermes-style runners, OpenClaw-style coordinators, and custom scripts can all participate through the same adapter shape.
