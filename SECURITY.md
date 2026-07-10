# Security Policy

## Supported Versions

Security fixes target the latest released minor version of Krystal Quorum.

## Security Model

Krystal Quorum reviews markdown plans. It does not execute the plan, edit code, deploy services, or grant authority to an agent.

- The default `mock`, `ollama`, and `openai` reviewers do not run shell commands.
- Command reviewers are opt-in and must be configured explicitly in TOML.
- API keys are read from environment variables only.
- Review artifacts are written under the configured output directory.
- Reviewer output is advisory and should be triaged before implementation.

When using command reviewers, treat the configured command as trusted local automation. Prefer read-only or sandboxed wrappers where your agent runtime supports them.

Command reviewers inherit the parent process environment by default, including API keys or other secrets present in your shell. Prefer wrapper scripts that pass an allowlisted environment when running third-party reviewer tools.

## Two-Gate Inputs And Artifacts

Repository-bound plan approvals write unsigned receipts. They link local
artifacts and repository state, but do not attest to an actor or authorize a
commit, push, deployment, or other side effect. Agent skills are policy
automation only; the GitHub Action is the enforceable CI boundary.

Review artifacts can contain plans, diff patches, reviewer prompts, and
findings. Treat them as sensitive: do not commit them or upload them casually.
Local diff review includes eligible untracked files by default and persists them
locally with the review artifacts. Pass `--no-include-untracked` to omit their
content. External reviewers additionally require the explicit
`--allow-untracked-external` opt-in before captured untracked content can be
sent across the reviewer boundary. Secret-looking input remains blocked for
external reviewers unless explicitly allowed. Hosted diff review is excluded
from v0.7.

## Reporting

Please report security issues through GitHub security advisories or by opening a private contact channel with the maintainers. Do not include API keys, private prompts, or proprietary review artifacts in public issues.
