# Krystal Quorum V1 Public Repo Spec

## Purpose

Krystal Quorum is a public, developer-first CLI that reviews an AI coding plan before an agent writes code. It helps developers catch vague requirements, missing acceptance criteria, contradictions, unsafe assumptions, and rollback/test gaps while the plan is still cheap to fix.

The project is a trust-building open-source release. It should be useful on its own for solo developers and small teams, while creating a natural path toward future Krystal Unity products for policy, audit history, dashboards, managed reviewer routing, and team governance.

## Public Positioning

Krystal Quorum is not an agent orchestrator and not a code generator.

One-line promise:

> Review the plan before your AI coding agent creates the mess.

Target users:

- AI-heavy solo developers using Codex, Claude Code, Cursor, Aider, OpenCode, or local agents.
- Small engineering teams adopting AI coding workflows.
- Agent-framework users who need a pre-dispatch review gate before implementation.

## V1 Scope

V1 ships a real local CLI:

```bash
krystal-quorum review plan.md
```

The command reads a markdown plan and writes an append-only review run directory containing:

- copied input plan;
- plan SHA256;
- raw reviewer outputs;
- reconciled verdict JSON;
- human-readable summary markdown;
- optional annotated plan markdown.

V1 review behavior:

- Round 1 independent reviewer pass.
- Optional Round 2 cross-audit where reviewers see peer findings.
- Author-skip support through config or CLI flag.
- Abstained reviewer state for crashed, unavailable, or timed-out reviewers.
- Reconciler that separates consensus blockers, singleton blockers, contradictions, and unresolved human decisions.
- Exit codes suitable for shell and CI:
  - `0` approve;
  - `1` revise;
  - `2` block;
  - `3` runtime/config error.

V1 integrations:

- Local CLI is primary.
- GitHub Action wrapper runs the same CLI and uploads review artifacts.
- Hermes/OpenClaw skill pack tells agent runtimes when and how to run Krystal Quorum before coding.

## Non-Goals

V1 does not:

- generate code;
- run a full agent swarm;
- manage worktrees;
- deploy applications;
- own project memory;
- replace human review;
- decide whether a plan is approved without human triage;
- require Krystal Unity infrastructure.

## Public-Safe Boundary

The public repo must not include:

- private server paths, hostnames, scripts, service names, or infrastructure details;
- private long-term memory, knowledge-store, or handover implementation details;
- private coordination-bus internals beyond generic optional integration docs;
- terminal/session management docs from internal operations;
- internal model-role maps;
- private product, customer, or partner-specific examples;
- provider credentials, internal IPs, or private model routing;
- live-loop operational doctrine tied to private products;
- proprietary reviewer-selection heuristics.

Public examples must use synthetic plans only.

## Repo Shape

```text
krystal-quorum/
  README.md
  pyproject.toml
  src/krystal_quorum/
    __init__.py
    __main__.py
    cli.py
    config.py
    models.py
    prompts.py
    reconcile.py
    persist.py
    reviewers/
      __init__.py
      base.py
      mock.py
      ollama.py
      openai_compatible.py
  examples/
    bad-plan.md
    reviewed-output/
  integrations/
    github-action/
      action.yml
      README.md
    hermes-skill/
      SKILL.md
    openclaw-skill/
      SKILL.md
  tests/
    test_cli.py
    test_models.py
    test_reconcile.py
    test_persist.py
    test_mock_review.py
```

## CLI Design

Primary command:

```bash
krystal-quorum review plan.md
```

Useful options:

```bash
krystal-quorum review plan.md \
  --config krystal-quorum.toml \
  --out-dir .krystal-quorum/reviews \
  --reviewers mock,ollama:qwen2.5:14b,openai:gpt-4.1 \
  --round2 \
  --author codex
```

V1 should default to a mock reviewer when no model config exists, so the tool is demonstrable immediately after install. Real reviewer adapters should be opt-in through CLI flags or config.

## Config Shape

Example `krystal-quorum.toml`:

```toml
[review]
round2 = false
out_dir = ".krystal-quorum/reviews"
author = "codex"

[[reviewers]]
id = "local-qwen"
provider = "ollama"
model = "qwen2.5:14b"
role = "system_diagnosis"

[[reviewers]]
id = "api-reviewer"
provider = "openai_compatible"
model = "gpt-4.1"
base_url = "https://api.openai.com/v1"
env_key = "OPENAI_API_KEY"
role = "code_audit"
```

## Reviewer Contract

Reviewers return strict JSON:

```json
{
  "reviewer": "local-qwen",
  "verdict": "REVISE",
  "confidence": 0.82,
  "blocking_issues": [
    {
      "id": "B1",
      "section": "Acceptance",
      "claim": "The plan never defines the expected CLI exit codes.",
      "evidence": "No exit-code section exists."
    }
  ],
  "suggestions": [
    {
      "id": "S1",
      "section": "Testing",
      "claim": "Add a fixture for malformed reviewer JSON.",
      "rationale": "The reconciler should not fail the whole run when one reviewer misbehaves."
    }
  ],
  "per_clause": {
    "acceptance.1": "SATISFIED",
    "acceptance.2": "UNSATISFIED"
  }
}
```

Canonical verdicts:

- `APPROVE`
- `REVISE`
- `BLOCK`
- `ABSTAIN`

## GitHub Action Scope

The GitHub Action is a wrapper around the CLI. V1 action behavior:

- install Krystal Quorum;
- run `krystal-quorum review <plan_path>`;
- upload the generated review directory as an artifact;
- fail or warn based on configured threshold.

The action should not require a hosted Krystal Quorum service.

## Hermes/OpenClaw Skill Scope

The skill pack should instruct compatible agent runtimes to:

1. Identify when a task is non-trivial, high-risk, or underspecified.
2. Write the proposed implementation plan to a markdown file.
3. Run `krystal-quorum review`.
4. Read the reconciled summary.
5. Revise the plan when findings are material.
6. Ask the operator before implementation when the verdict is `REVISE` or `BLOCK`.

The skill must treat reviewer outputs as advisory, not authority.

## Launch-Ready Criteria

V1 is launch-ready when:

- `pipx install .` or `uv tool install .` exposes `krystal-quorum`;
- `krystal-quorum review examples/bad-plan.md --reviewers mock` works with no external keys;
- at least one real local reviewer adapter works with Ollama;
- one OpenAI-compatible adapter works with BYOK;
- tests cover schema validation, reconciliation, persistence, CLI exit codes, and abstained reviewers;
- README explains value in under 30 seconds;
- examples contain no internal KU details;
- GitHub Action wrapper exists and is documented;
- Hermes/OpenClaw skill packs exist and are documented.

## Spec Self-Review

- Placeholder scan: no unresolved placeholder markers.
- Scope check: V1 is focused on a local review CLI plus thin integrations.
- Leakage check: internal KU systems are named only as private exclusions, not implemented or documented.
- Ambiguity check: reviewer outputs are advisory, human triage remains required, and Krystal Quorum is not positioned as an orchestrator.
