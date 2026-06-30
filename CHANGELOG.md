# Changelog

## 0.6.7 - 2026-06-30

- Fixed the GitHub Action so artifact outputs are emitted even when Quorum
  correctly exits non-zero for `REVISE`, `BLOCK`, or runtime errors.
- Added first-class hosted Action inputs for `api-token` and `api-base-url`.
- Added a `latest-output-dir` Action output for the newest per-run artifact
  directory.
- Made mock-only Action runs print a CI warning because `mock` is a structural
  smoke test, not a real multi-AI review.

## 0.6.6 - 2026-06-30

- Added a root GitHub Action for Marketplace-ready multi-AI plan review in CI.
- Repositioned the public README and package metadata around multi-AI quorum
  review before coding agents write code.
- Updated GitHub Action docs to use the root action path and pinned
  `krystal-quorum==0.6.6` package installs.

## 0.6.5 - 2026-06-29

- Added `--format pretty` support for hosted Quorum reviews.
- Documented that hosted packs choose their own server-side reviewer mix and
  round strategy.
- Added a GitHub Action example for `hosted:quick` with a `KU_TOKEN` secret.
- Persist hosted `failed_no_charge` responses locally and print an explicit
  no-credit-charged message when hosted quorum collapses before a usable review.

## 0.6.4 - 2026-06-28

- Added hosted Quorum CLI mode with `hosted:quick`, `hosted:standard`, and
  `hosted:council` reviewer packs.
- Added hosted API token support through `--api-token` or `KU_TOKEN`.
- Persisted hosted responses into the normal local artifact directory shape.
- Rejected mixed hosted/local reviewer lists in the first hosted adapter pass.

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
