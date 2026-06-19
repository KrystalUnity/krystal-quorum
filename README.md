# Krystal Quorum

Review the plan before your AI coding agent creates the mess.

Krystal Quorum is a local CLI that reviews markdown implementation plans with one or more independent reviewers, then writes a reconciled human-triage summary. It is designed for developers using AI coding agents who want to catch vague requirements, missing acceptance criteria, contradictions, unsafe assumptions, rollback gaps, and test gaps before code is written.

Krystal Quorum is not an agent orchestrator and not a code generator. It is the review gate before implementation.

## Quickstart

```bash
python -m pip install -e ".[dev]"
krystal-quorum review examples/bad-plan.md --reviewers mock
```

The command writes an append-only review run under `.krystal-quorum/reviews/`.

## Reviewers

Mock reviewer, no keys required:

```bash
krystal-quorum review examples/bad-plan.md --reviewers mock
```

Local Ollama reviewer:

```bash
krystal-quorum review plan.md --reviewers ollama:qwen2.5:14b
```

OpenAI-compatible reviewer:

```bash
set OPENAI_API_KEY=...
krystal-quorum review plan.md --reviewers openai:gpt-4.1
```

Use `OPENAI_BASE_URL` to point at another OpenAI-compatible provider.

## Exit Codes

- `0`: approve
- `1`: revise
- `2`: block
- `3`: runtime or configuration error

Reviewer outputs are advisory. A human should triage the findings before implementation.
