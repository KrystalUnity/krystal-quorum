# Krystal Quorum

[![CI](https://github.com/KrystalUnity/krystal-quorum/actions/workflows/ci.yml/badge.svg)](https://github.com/KrystalUnity/krystal-quorum/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Review the plan before your AI coding agent creates the mess.

Krystal Quorum is a local CLI that reviews markdown implementation plans with one or more independent reviewers, then writes a reconciled human-triage summary. It is designed for developers using AI coding agents who want to catch vague requirements, missing acceptance criteria, contradictions, unsafe assumptions, rollback gaps, and test gaps before code is written.

Krystal Quorum is not an agent runtime and not a code generator. It is a review step before implementation.

## Quickstart

```bash
git clone https://github.com/KrystalUnity/krystal-quorum.git
cd krystal-quorum
python -m pip install -e ".[dev]"
krystal-quorum review examples/bad-plan.md --reviewers mock
```

The command writes an append-only review run under `.krystal-quorum/reviews/`.

## 60-Second Demo

Run the no-key mock reviewer against the deliberately weak example plan:

```bash
krystal-quorum review examples/bad-plan.md --reviewers mock
```

Example output:

```json
{
  "schema_version": "1.1",
  "verdict": "REVISE",
  "confidence": 0.9,
  "reviewers_used": ["mock"],
  "diversity": "ok",
  "diversity_reason": null,
  "diversity_reviewers": [{"reviewer": "mock", "backend": "mock", "family": "mock"}],
  "output_dir": ".krystal-quorum/reviews/bad-plan_20260619-102618"
}
```

`REVISE` exits with code `1`, so CI scripts can fail fast when a plan needs
work. Review artifacts are written locally and ignored by git.

## Reviewers

Krystal Quorum is bring-your-own-LLM. The CLI sends the plan text to each
configured reviewer, asks for strict JSON, then reconciles the responses into
one human-triage summary.

Use the mock reviewer first to prove the workflow works. It uses no network and
requires no keys:

```bash
krystal-quorum review examples/bad-plan.md --reviewers mock
```

### Local Ollama

Start Ollama with any model you already have available, then pass the model name
after `ollama:`:

```bash
krystal-quorum review plan.md --reviewers ollama:qwen2.5:14b
```

Prefer instruct-tuned models for reviewer adapters. Reasoning-heavy models can
spend most of the default timeout on internal thinking and may abstain if they
do not return the strict JSON contract in time.

If Ollama is running somewhere other than `http://localhost:11434`, set
`OLLAMA_BASE_URL`:

```bash
OLLAMA_BASE_URL=http://192.168.1.20:11434 krystal-quorum review plan.md --reviewers ollama:your-model
```

### OpenAI API

```bash
export OPENAI_API_KEY=...
krystal-quorum review plan.md --reviewers openai:gpt-4.1
```

PowerShell:

```powershell
$env:OPENAI_API_KEY = "..."
krystal-quorum review plan.md --reviewers openai:gpt-4.1
```

### OpenAI-Compatible Servers

Any server that exposes an OpenAI-compatible `/chat/completions` endpoint can be
used by setting `OPENAI_BASE_URL`. This is how you connect hosted providers,
gateway services, or local inference servers that mimic the OpenAI API.

```bash
export OPENAI_API_KEY=your-provider-key-or-local-placeholder
export OPENAI_BASE_URL=http://localhost:1234/v1
krystal-quorum review plan.md --reviewers openai:your-model
```

PowerShell:

```powershell
$env:OPENAI_API_KEY = "your-provider-key-or-local-placeholder"
$env:OPENAI_BASE_URL = "http://localhost:1234/v1"
krystal-quorum review plan.md --reviewers openai:your-model
```

### Local Command Reviewers

Use `command:<name>` reviewers when you already have local coding agents or
review scripts installed. Command reviewers receive the full review prompt on
stdin and can return the strict reviewer JSON on stdout.

```toml
# krystal-quorum.toml
[reviewers.local-codex]
type = "command"
command = ["codex", "exec", "--sandbox", "read-only", "--ephemeral", "-"]
timeout_s = 180
```

Then run:

```bash
krystal-quorum review plan.md --config krystal-quorum.toml --reviewers command:local-codex
```

If a tool writes its final answer to a file, configure `output_file`. This is
useful for wrappers that start a detached local agent process and collect the
final review later.

```toml
[reviewers.local-agent]
type = "command"
command = ["bash", "reviewers/local-agent-review.sh"]
timeout_s = 30
output_file = ".krystal-quorum/tmp/local-agent-review.json"
wait_for_output_s = 300
```

Command reviewers are intentionally generic. They can wrap installed CLIs,
local scripts, or remote shells. If a command times out, exits without output,
or returns unparseable text, Krystal Quorum records that reviewer as `ABSTAIN`
instead of blocking the whole run.

Try the bundled command-reviewer example:

```bash
krystal-quorum review examples/bad-plan.md --config examples/command-reviewer.toml --reviewers command:example-local
```

### Multiple Reviewers

Pass a comma-separated reviewer list to compare independent model reviews:

```bash
krystal-quorum review plan.md --reviewers ollama:model-a,openai:model-b
```

Add `--round2` when you want reviewers to cross-audit each other's findings
before the final reconciliation:

```bash
krystal-quorum review plan.md --reviewers ollama:model-a,openai:model-b --round2
```

Round 2 artifacts include `round2_delta` and per-reviewer before/after verdicts
so you can see whether cross-audit changed any reviewer positions.
When `--round2` is used, the short CLI JSON also includes `round2_comparisons`
for scripts that do not read the full artifact directory.

### Reviewer Diversity

Krystal Quorum reports reviewer diversity in both CLI output and persisted
artifacts. Diversity is `low` when any two reviewers resolve to the same model
family, such as `openai:gpt-4.1` and `openai:gpt-4.1-mini`, or
`ollama:qwen2.5:14b` and `ollama:qwen2.5:32b`.

Use `--require-diversity` to fail closed before review when reviewers are too
correlated:

```bash
krystal-quorum review plan.md \
  --reviewers ollama:qwen2.5:14b,ollama:qwen2.5:32b \
  --require-diversity
```

Command reviewers use the command name as their family by default. You can
override that in config:

```toml
[reviewers.local-agent-a]
type = "command"
command = ["bash", "reviewers/a.sh"]
family = "local-agent"
```

## Reconciliation Model

Krystal Quorum is safety-biased rather than majority-rule voting. A single
`BLOCK` verdict blocks the merged result, and a single unresolved blocking issue
forces at least `REVISE`. When two or more reviewers report substantially
similar blocking issues, Quorum promotes that finding to a shared blocker.

Reviewers are asked to emit `per_clause` statuses for common plan clauses such
as acceptance criteria, rollback, tests, and safety assumptions. Contradictory
clause statuses are surfaced for human triage instead of being averaged away.

## Exit Codes

- `0`: approve
- `1`: revise
- `2`: block
- `3`: runtime or configuration error

Reviewer outputs are advisory. A human should triage the findings before implementation.

## License

Apache-2.0.
