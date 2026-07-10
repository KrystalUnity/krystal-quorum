# Agent Import Packs

Krystal Quorum ships project-local import packs for common AI coding agent
workflows. Each pack automatically applies the same two-gate policy: a
multi-AI quorum checks the commitment-bearing plan before coding, then checks
whether the implementation kept its promises after normal tests. This is policy
automation, not enforcement; the GitHub Action is the hard CI boundary.

## Supported Targets

```bash
krystal-quorum init --list-targets
```

Targets:

- `claude-code`: Claude Code skill plus optional slash command.
- `codex`: project-local Codex-style skill.
- `copilot`: GitHub Copilot project skill.
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

That file defines the common two-gate workflow:

1. Write or locate a markdown plan with recognized commitment sections.
2. Use the project's configured real reviewer profile, or ask the human once
   when no profile exists.
3. Run a repository-bound plan review before edits and retain its
   `approval.json` path on `APPROVE`.
4. Implement only the approved scope and run the normal test suite.
5. Run verified diff review with that same approval artifact and reviewer
   profile.
6. Remediate `REVISE` or `BLOCK`, or present unresolved human triage. Report
   both verdicts and artifact paths.

The target-specific files adapt that workflow to each agent's expected import
shape. They never automatically commit, push, or deploy. `mock` is for
installation smoke tests only, not a real review.

## Reviewers And Artifacts

Use local command reviewers for installed coding agents, Ollama for local
models, or API-compatible reviewers when the data boundary is acceptable.
Reviewer artifacts can contain plans, patches, prompts, and findings: do not
commit them or upload them casually. Verified local approvals are unsigned
receipts, not identity attestations. Local diff review includes eligible
untracked files by default and persists them locally with its artifacts. Use
`--no-include-untracked` when those files must be omitted. External reviewers
add a second boundary: captured untracked content requires the explicit
`--allow-untracked-external` opt-in. Secret-looking input also requires an
explicit external-review opt-in.

GitHub Actions run standalone diff review against exact pull-request SHAs and
therefore report unverified plan provenance in v0.7. Hosted diff review is
excluded from this release.

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
