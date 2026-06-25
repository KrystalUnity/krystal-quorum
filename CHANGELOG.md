# Changelog

## 0.6.3 - 2026-06-25

- Added `krystal-quorum demo` for a no-clone, no-key bundled mock review.
- Bundled the good and bad demo plans inside the wheel.
- Updated README, demo docs, and the animated terminal asset around the
  two-command PyPI onboarding path.

## 0.6.2 - 2026-06-25

- Published Krystal Quorum to PyPI.
- Restored the public Quickstart to the one-line PyPI install path.
- Kept source checkout install documented as the development fallback.

## 0.6.1 - 2026-06-25

- Fixed public install guidance to use a source checkout until the package is
  published to PyPI.
- Promoted the pretty terminal output and agent import packs in the README
  quickstart path.
- Updated demo docs and the animated terminal asset to show `--format pretty`.
- Added a public readiness test so unpublished PyPI install commands do not
  reappear in launch docs.

## 0.6.0 - 2026-06-24

- Added universal agent import packs with `init --target codex|claw|opencode|all` and `init --list-targets`.
- Installed a shared `.krystal-quorum/agents/quorum-review.md` workflow with every agent pack.
- Added `--format json|pretty`; JSON remains the default and pretty output gives a terminal-friendly review card.
- Added public docs for agent import packs and the reviewer prompt contract.

## 0.5.3 - 2026-06-24

- Expanded the reviewer rubric contract with `security.risk`, `dependencies.scope`, and `observability.plan` clause keys.
- Normalized aliases for the expanded rubric keys before contradiction detection.
- Added optional Ollama reasoning controls via `[ollama] think = false` and `num_predict`.
- Documented that the single-`BLOCK` veto is intentional fail-safe behavior, not majority voting.

## 0.5.2 - 2026-06-24

- Added a plan-size guard with rough token estimate before reviewers are built.
- Made untagged JSON extraction prefer the last complete reviewer-shaped object, reducing schema-echo false parses.
- Restricted reasoning-only response fallback to explicit `<json>...</json>` payloads.
- Added public benchmark fixtures and a JSONL benchmark runner for collecting single-reviewer vs quorum evidence.

## 0.5.1 - 2026-06-24

- Forced collapsed multi-reviewer quorums to `REVISE` and surfaced quorum health in CLI JSON and summaries.
- Added transport retries for transient Ollama and OpenAI-compatible reviewer failures before abstaining.
- Penalized system confidence for partial quorum, low reviewer diversity, singleton blockers, and contradictions.
- Normalized known `per_clause` key variants before contradiction detection and flagged unknown keys for human triage.
- Serialized Round 2 peer findings as JSON instead of Python repr.
- Added Python 3.12 to CI and documented command-reviewer environment inheritance.

## 0.5.0 - 2026-06-24

- Added `krystal-quorum init --target claude-code|hermes|openclaw` for project-local agent integration templates.
- Added package build metadata and CI build/check steps for PyPI readiness.
- Added public architecture docs for deterministic consensus matching and local command reviewers.
- Added release, security, contribution, issue-template, and demo polish for public adoption.
- Added deterministic good/bad/agent example plans and a lightweight terminal demo asset.

## 0.4.0

- Promoted deterministic consensus matching with persisted `issue_clusters`.
- Added retry-on-malformed reviewer output.
- Added reviewer diversity reporting and round-2 comparison metrics.
- Parallelized round-2 reviewer execution.

## 0.3.x

- Added command reviewers, filename-safe reviewer artifacts, stricter prompt schema, and fixed per-clause keys.

## 0.2.x

- Added persisted review runs, reconciled verdicts, and package version alignment.

## 0.1.x

- Initial local CLI prototype with mock and LLM-backed review adapters.
