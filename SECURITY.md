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

## Reporting

Please report security issues through GitHub security advisories or by opening a private contact channel with the maintainers. Do not include API keys, private prompts, or proprietary review artifacts in public issues.
