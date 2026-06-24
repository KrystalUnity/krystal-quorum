# Changelog

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
