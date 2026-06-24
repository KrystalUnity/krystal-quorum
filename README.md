# Krystal Quorum

[![CI](https://github.com/KrystalUnity/krystal-quorum/actions/workflows/ci.yml/badge.svg)](https://github.com/KrystalUnity/krystal-quorum/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

```text
+-- Krystal Quorum ------------------------+
| Review the plan before agents edit code. |
+------------------------------------------+
```

Review the plan before your AI coding agent creates the mess.

Krystal Quorum is a local CLI that reviews markdown implementation plans with one or more independent reviewers, then writes a reconciled human-triage summary. It is designed for developers using AI coding agents who want to catch vague requirements, missing acceptance criteria, contradictions, unsafe assumptions, rollback gaps, and test gaps before code is written.

Krystal Quorum is not an agent runtime and not a code generator. It is a review step before implementation.

## Quickstart

```bash
python -m pip install krystal-quorum
git clone https://github.com/KrystalUnity/krystal-quorum.git
cd krystal-quorum
krystal-quorum review examples/bad-plan.md --reviewers mock
```

If you are already in a checkout, only the install and review commands are
needed. The command writes an append-only review run under
`.krystal-quorum/reviews/`.

By default Quorum rejects plans over 120,000 characters before reviewers are
constructed, with a rough token estimate in the error. Use `--max-plan-chars`
to raise the limit or `--max-plan-chars 0` to disable the guard for a
controlled run.

For development from a checkout:

```bash
python -m pip install -e ".[dev]"
```

Agent integration packs for Claude Code, Hermes-style runners, OpenClaw-style
coordinators, and CI live in [docs/agent-integrations.md](docs/agent-integrations.md).

Install project-local agent skills with:

```bash
krystal-quorum init --target claude-code
krystal-quorum init --target hermes
krystal-quorum init --target openclaw
```

## 60-Second Demo

Run the no-key mock reviewer against the deliberately weak example plan:

```bash
krystal-quorum review examples/bad-plan.md --reviewers mock
```

Example output:

```json
{
  "schema_version": "1.2",
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

Now run the fixed plan:

```bash
krystal-quorum review examples/good-plan.md --reviewers mock
```

The mock reviewer sees explicit acceptance criteria and returns `APPROVE`
with exit code `0`. See [docs/demo.md](docs/demo.md) for a short transcript and
terminal card.

## Reviewers

Krystal Quorum is bring-your-own-LLM. The CLI sends the plan text to each
configured reviewer, asks for strict JSON, then reconciles the responses into
one human-triage summary.

If a reviewer returns malformed text instead of the strict JSON contract,
Krystal Quorum retries that reviewer once with a JSON-only reminder. The final
artifact records the retry count and preserves raw text from both attempts.
Transient HTTP failures from Ollama or OpenAI-compatible reviewers are retried
before the reviewer is marked `ABSTAIN`.
When a reviewer omits `<json>` tags, Quorum searches for complete reviewer JSON
objects and prefers the last one, which reduces false parses when a model echoes
the schema before its final answer. Reasoning-only responses are parsed only
when they contain explicit `<json>...</json>` tags.

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
or still returns unparseable text after the one-shot parse retry, Krystal
Quorum records that reviewer as `ABSTAIN` instead of blocking the whole run.
Multi-reviewer runs surface partial abstentions in `unresolved_for_human`; if a
multi-reviewer quorum collapses to only one usable reviewer, the merged verdict
is forced to `REVISE` for human triage.

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

Low diversity does not change the verdict by itself, but it reduces the
reported system confidence.

## Reconciliation Model

Krystal Quorum is safety-biased rather than majority-rule voting. A single
`BLOCK` verdict blocks the merged result, and a single unresolved blocking issue
forces at least `REVISE`. When two or more reviewers report substantially
similar blocking issues, Quorum promotes that finding to a shared blocker.

Consensus matching is deterministic and explainable. Quorum groups reviewer
findings with a small public concept matcher for common review areas such as
acceptance criteria, rollback, tests, security, dependencies, and observability.
It does not use embeddings or hidden model calls to decide whether two issues
match. Persisted review artifacts include `issue_clusters` with members, direct
match edges, and match reasons.

Support-overlap consensus requires at least two shared support terms and an
overlap coefficient of at least `0.50`. Absence-style findings require a shared
topic-specific gap term, so broad words like "missing" or generic section names
like "Plan" are not enough to create consensus.

Set `KRYSTAL_QUORUM_CONSENSUS_MATCHER=legacy` to temporarily restore the older
token-overlap grouping behavior. This is a behavior rollback, not a schema
downgrade: schema-1.1-only consumers should pin a v0.3.x release or revert the
v0.4 change.

Reviewers are asked to emit `per_clause` statuses for common plan clauses such
as acceptance criteria, rollback, tests, and safety assumptions. Contradictory
clause statuses are surfaced for human triage instead of being averaged away.
Common key variants such as `acceptance_criteria` are normalized before
comparison; unknown keys are flagged in `unresolved_for_human`.

The `confidence` field is a system-adjusted signal. It starts from reviewer
self-reported confidence, then discounts weak quorum health, low diversity,
singleton blockers, and contradictions.

Architecture notes:

- [Consensus matching](docs/architecture/consensus-matching.md)
- [Local command reviewers](docs/architecture/local-command-reviewers.md)

Benchmark fixtures live in [benchmarks/](benchmarks/). They provide a small,
public way to compare single-reviewer and multi-reviewer behavior without
claiming more evidence than the project has collected.

## Exit Codes

- `0`: approve
- `1`: revise
- `2`: block
- `3`: runtime or configuration error

Reviewer outputs are advisory. A human should triage the findings before implementation.

## License

Apache-2.0.
