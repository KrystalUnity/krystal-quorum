# Krystal Quorum

Review the plan before your AI coding agent creates the mess.

Krystal Quorum is a local CLI that reviews markdown implementation plans with one or more independent reviewers, then writes a reconciled human-triage summary. It is designed for developers using AI coding agents who want to catch vague requirements, missing acceptance criteria, contradictions, unsafe assumptions, rollback gaps, and test gaps before code is written.

Krystal Quorum is not an agent runtime and not a code generator. It is a review step before implementation.

## Quickstart

```bash
python -m pip install -e ".[dev]"
krystal-quorum review examples/bad-plan.md --reviewers mock
```

The command writes an append-only review run under `.krystal-quorum/reviews/`.

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

## Exit Codes

- `0`: approve
- `1`: revise
- `2`: block
- `3`: runtime or configuration error

Reviewer outputs are advisory. A human should triage the findings before implementation.
