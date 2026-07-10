# ADR: Plan-to-Code Evidence

## Status

Implemented and verified in v0.7.0.

## Context

Krystal Quorum currently reviews an implementation plan before an AI coding agent edits code. That catches weak acceptance criteria, unsafe assumptions, missing rollback steps, and vague tests before implementation begins.

The next useful gate is not generic pull-request review. It is a second, narrower question:

> Did the agent implement the plan that passed review, and what evidence supports that conclusion?

A plain `--plan` plus Git diff comparison is useful, but it does not prove that the plan was reviewed, that it remained unchanged, or that the diff starts from the same baseline. It also produces free-form findings rather than a stable coverage view of the plan's commitments.

This decision adds an auditable plan-to-code evidence chain while preserving a simpler standalone comparison mode.

## Product Promise

Krystal Quorum will support two connected gates:

1. **Plan gate:** multiple reviewers pressure-test the implementation plan before code exists.
2. **Diff gate:** multiple reviewers compare the resulting implementation with that plan before merge or deploy.

Verified mode binds those gates with hashes and an exact Git baseline. Standalone mode compares any reference plan with a diff but labels the plan provenance as unverified.

The public positioning is:

> A multi-AI quorum checks the plan before coding, then checks whether the implementation kept its promises.

## Goals

- Prove which plan text, Git baseline, and implementation diff were compared.
- Produce a commitment-by-commitment coverage matrix with file and line evidence.
- Detect missing commitments, partial implementation, and unplanned scope.
- Reuse the existing reviewer transports, diversity analysis, round 2, and artifact model.
- Work with local Ollama models, API reviewers, and trusted command reviewers.
- Fail closed before reviewer execution when provenance, Git, size, or data-boundary checks fail.
- Make CI findings visible without requiring users to download an artifact archive.
- Preserve all v0.6 plan-review behavior and output contracts.

## Non-Goals

- Generic style, lint, or pull-request review.
- Executing tests or proving runtime correctness.
- Cryptographically signing approval receipts in v0.7.
- Portable verified-receipt attestation in GitHub Actions.
- Automatically chunking or summarizing arbitrarily large diffs.
- Hiding excluded files or silently truncating reviewer input.
- Public hosted diff review before a structured server contract is deployed and verified.
- Replacing existing code scanners, secret scanners, or human review.
- Adding a new runtime dependency; v0.7 uses the standard library and existing package dependencies.

## Terminology

### Commitment

A discrete promise extracted from a known plan section. v0.7 recognizes:

- acceptance criteria
- planned scope, files, and modules
- tests and verification
- rollback
- security and safety
- dependencies and migrations
- observability

Each commitment has a stable ID, category, source text, source line, and optional descendant-heading group. Explicit IDs such as `AC-7` are preserved. Otherwise Quorum assigns deterministic category-and-order IDs such as `AC-1` and `TEST-2`.

Every extracted item is required; v0.7 has no optional-commitment syntax. The category prefixes are `AC` for acceptance, `SCOPE` for planned scope, `TEST` for tests and verification, `RB` for rollback, `SEC` for security and safety, `DEP` for dependencies and migrations, and `OBS` for observability.

The parser recognizes exactly two explicit-ID forms at the start of an item, using case-insensitive matching:

```text
^\[(AC|SCOPE|TEST|RB|SEC|DEP|OBS)-([1-9][0-9]*)\]\s+
^(AC|SCOPE|TEST|RB|SEC|DEP|OBS)-([1-9][0-9]*):\s+
```

Stored IDs are normalized to uppercase. A prefix that does not match the containing category is a preflight error.

### Approval Receipt

An unsigned JSON receipt emitted only when a repository-bound plan review ends in `APPROVE` and contains at least one required commitment in any recognized category. It records the plan hash, exact Git baseline, reviewer set, diversity, commitments, tool version, and reconciled-result hash.

The receipt proves which local artifacts were compared. It does not prove the identity of the person or process that created it, and public documentation must not describe it as a digital signature or external attestation.

### Diff Snapshot

A deterministic capture of the tracked patch, eligible untracked files, changed-file metadata, resolved Git refs, and hashes used for review.

### Plan Provenance

- `verified_receipt`: the plan hash and Git baseline match a valid approval receipt.
- `unverified_reference`: the user supplied a plan without an approval receipt.

## User Flows

### Verified Local Flow

Before implementation:

```bash
krystal-quorum review docs/plans/change.md \
  --bind-repo . \
  --reviewers ollama:qwen2.5:14b,command:local-codex \
  --config krystal-quorum.toml \
  --round2 \
  --format pretty
```

An approved, repository-bound run writes `approval.json` inside its artifact directory.

After implementation:

```bash
krystal-quorum diff \
  --plan docs/plans/change.md \
  --approval .krystal-quorum/reviews/change_.../approval.json \
  --repo . \
  --reviewers ollama:qwen2.5:14b,command:local-codex \
  --config krystal-quorum.toml \
  --round2 \
  --format pretty
```

When `--approval` is present, its baseline is authoritative. `--base` is rejected rather than allowed to override the approved baseline.

### Standalone Comparison

```bash
krystal-quorum diff \
  --plan docs/plans/change.md \
  --repo . \
  --base main \
  --reviewers openai:gpt-4.1,openai:o4-mini \
  --no-include-untracked \
  --round2 \
  --format pretty
```

The result is labelled `Plan provenance: unverified reference`. It must not be presented as proof that the plan passed the first gate.

### Preflight-Only Inspection

```bash
krystal-quorum diff \
  --plan docs/plans/change.md \
  --repo . \
  --base main \
  --reviewers openai:gpt-4.1,openai:o4-mini \
  --dry-run
```

`--dry-run` performs Git subprocess capture, size checks, commitment extraction, secret-pattern checks, and reviewer-boundary classification without constructing reviewer clients, invoking command reviewers or agent CLIs, or making network requests. It prints hashes, character counts, changed-file counts, reviewer destinations, and warning classes, but never prints plan or diff contents.

## Agent-Native Execution

v0.7 defines two complementary execution levels:

`agent_policy`: project-local skills/instructions tell supported coding agents to author a commitment-bearing plan, run bound review before edits, handle `REVISE` by revising and rerunning until `APPROVE` or returning to the human, implement, run verified diff review, and present the final verdict/result.

`ci_enforcement`: the GitHub Action is the hard enforcement boundary: it runs standalone diff review against exact PR SHAs and can fail the check independently of agent behavior.

After one-time `pip install krystal-quorum` and `krystal-quorum init --target ...`, ordinary non-trivial coding tasks should not require the human to type Quorum commands. Skill discovery is agent-controlled and is not a hard enforcement boundary; teams requiring enforcement use CI.

## Repository-Bound Plan Review

The existing `review` command remains unchanged unless `--bind-repo <dir>` is supplied.

With `--bind-repo`:

1. Quorum resolves the repository root and `HEAD` before reviewer execution.
2. The plan must be inside the repository, tracked at `HEAD`, and unchanged in a clean index and worktree. The configured artifact output directory is excluded from this cleanliness check whether or not Git already ignores it; other untracked files make the baseline ineligible.
3. It extracts commitments from the plan deterministically.
4. A bound plan with no required commitment in any recognized category fails preflight with exit code `3` before reviewer construction.
5. After reviewer reconciliation but before any artifact write, Quorum rechecks `HEAD`, the plan hash, and clean-worktree state using the same artifact-directory exclusion. A concurrent change then persists an ordinary review run without `approval.json` and exits `3`.
6. After successful revalidation, Quorum builds the receipt in memory and persists the normal review artifacts plus `approval.json` in the same run directory. Persistence failure exits `3` and reports any partial artifact directory.
7. `demo` and ordinary unbound `review` runs do not require Git and do not write approval receipts.

The v0.7 receipt schema is:

```json
{
  "schema_version": "krystal-quorum.approval.v1",
  "tool_version": "0.7.0",
  "created_at": "2026-07-10T00:00:00Z",
  "authenticity": "unsigned",
  "verdict": "APPROVE",
  "plan_path": "docs/plans/change.md",
  "plan_sha256": "...",
  "base_ref": "HEAD",
  "base_sha": "...",
  "reviewers_used": ["ollama:qwen2.5:14b", "command:local-codex"],
  "reviewer_families": ["qwen2.5", "codex"],
  "diversity": "ok",
  "reconciled_sha256": "...",
  "commitments": [
    {
      "id": "AC-1",
      "category": "acceptance",
      "text": "The CLI returns exit code 1 when the implementation is incomplete.",
      "source_line": 42
    }
  ]
}
```

Receipt and reconciled-result hashes use UTF-8 JSON with sorted keys and compact separators before SHA256. The receipt contains no API keys, raw reviewer responses, absolute repository paths, or remote URLs.

## Commitment Extraction

Commitment extraction is deterministic and does not call a model.

- Heading text is trimmed, lowercased, stripped of a trailing colon, and has internal whitespace collapsed. Matching is exact after normalization, not substring-based.
- The complete alias table is:

| Category | Prefix | Recognized normalized headings |
| --- | --- | --- |
| acceptance | `AC` | `acceptance`, `acceptance criteria`, `success criteria`, `definition of done` |
| scope | `SCOPE` | `scope`, `planned scope`, `implementation scope`, `implementation map`, `files`, `files to change`, `files and modules`, `files or modules expected to change` |
| tests | `TEST` | `tests`, `testing`, `test plan`, `test strategy`, `verification`, `verification plan`, `tests and verification` |
| rollback | `RB` | `rollback`, `rollback plan`, `recovery plan` |
| security | `SEC` | `security`, `safety`, `security and safety` |
| dependencies | `DEP` | `dependencies`, `migrations`, `dependencies and migrations` |
| observability | `OBS` | `observability`, `monitoring`, `telemetry` |

- A recognized heading at level N opens its category until the next heading at level N or higher.
- Lower-level descendant headings remain inside the category and are recorded as a group path. A top-level list or checklist item beneath them still becomes a commitment.
- Top-level means the item is not nested beneath another list item; it does not mean the item must immediately follow the category heading.
- Nested lines are retained as continuation text for their parent item.
- Explicit IDs matching the documented category prefixes are preserved and must match the category of their containing section.
- Generated IDs use the category prefix and one-based source order.
- Duplicate explicit IDs are a preflight error in bound and standalone modes.
- Source text is preserved exactly apart from line-ending normalization.

The plan SHA remains the authority. Generated IDs are stable for one approved plan snapshot and are not promised to survive edits to the plan.

## Approval Validation

When `--approval` is supplied, validation occurs before reviewers are constructed:

1. Parse the strict receipt schema and require `authenticity="unsigned"` and `verdict="APPROVE"`.
2. Require the sibling `reconciled.json`, validate its canonical hash against `reconciled_sha256`, and require its merged verdict to be `APPROVE`. This is an audit link, not a signature or external trust proof.
3. Hash the current plan and require an exact match.
4. Resolve the receipt's `base_sha` in the target repository.
5. For an explicit committed head, require `base_sha` to be an ancestor of `head_sha`.
6. For working-tree review, require `base_sha` to be an ancestor of the current `HEAD`.
7. Require freshly extracted commitment IDs and text to match the receipt.

Any mismatch exits `3` with one concise remediation and creates no review run directory. Users may re-review the changed plan or use standalone mode, but they cannot weaken a verified run by overriding the receipt baseline.

## Git Diff Capture

### Verified Mode

Verified mode compares the exact approved `base_sha` with the chosen committed head or current working tree. It does not recalculate a merge base.

If the implementation history no longer descends from the approved baseline, verified mode fails closed and tells the user to reapprove the rebased plan or use standalone comparison.

### Standalone Mode

Standalone committed-ref review uses merge-base semantics (`base...head`) because that matches common pull-request expectations. Working-tree review compares the resolved base ref with current `HEAD`, staged changes, unstaged changes, and eligible untracked files.

### Safe Git Invocation

All Git operations use argument arrays with `shell=False`. Patch generation includes:

```text
--find-renames --no-ext-diff --no-textconv --no-color --unified=<context-lines>
```

Changed-file parsing uses `--name-status -z` and NUL-delimited output so tabs, newlines, spaces, and non-ASCII paths cannot corrupt parsing. Refs are resolved to immutable SHAs before patch capture.

v0.7 enables rename detection but not copy detection. A copied file is represented as an added file unless Git reports another tracked status without Quorum requesting it. Tests assert this behavior instead of expecting `C` statuses.

The snapshot records:

- user-supplied refs
- resolved base SHA
- resolved head SHA, when applicable
- merge-base SHA in standalone committed-ref mode
- working-tree status
- changed files, including rename source and destination
- tracked patch
- synthetic patch sections for eligible untracked text files
- metadata markers for binary, symlink, submodule, unreadable, and other non-regular files
- canonical diff SHA256

Untracked previews never follow symlinks and never read sockets, FIFOs, devices, or paths that resolve outside the repository.

## Input Bounds

Quorum never silently truncates a plan or diff.

- Existing plan limit: `120000` characters.
- Default diff limit: `160000` characters.
- Default complete reviewer-input limit: `220000` characters.
- `--max-diff-chars` and `--max-review-chars` must be positive.
- Errors report actual characters, configured limits, and a rough token estimate.

Users may raise limits explicitly. Quorum does not claim that every reviewer supports the raised context size.

The complete-input limit is independent and intentionally stricter than the sum of the individual defaults. A plan and diff may each pass their own limit but still fail before reviewer construction when their combined document, commitments, and metadata exceed `--max-review-chars`.

`--context-lines` defaults to `20` and must be between `0` and `200`.

A plan with no extracted required commitment is a preflight error in bound and standalone modes, regardless of diff size, because there is no coverage subject. With one or more commitments, an empty diff produces a deterministic `REVISE` result and artifacts without spending reviewer calls.

## Reviewer Specification And Data Boundaries

Reviewer names must be parsed once into a normalized `ReviewerSpec`. The same object drives validation, diversity metadata, data-boundary checks, and reviewer construction. A separate parser must not duplicate `build_reviewers` string logic.

Each spec has:

- public reviewer ID
- backend type
- model family
- endpoint, when applicable
- `data_boundary`: `local`, `external`, or `unknown`

Boundary rules are fail-safe:

- `mock` is local.
- `hosted:*` is external and unsupported for diff review in v0.7.
- Ollama and OpenAI-compatible endpoints are local only when URL parsing proves a loopback address.
- Non-loopback and cloud-tagged endpoints are external.
- Command reviewers use explicit config metadata. A missing `data_boundary` is classified as unknown and is a configuration error for diff mode before the command runs.
- A command reviewer's `local` declaration is a user trust assertion, not sandbox enforcement.

Loopback detection uses URL parsing plus `ipaddress` checks for `localhost`, `127.0.0.0/8`, and `::1`.

`external` means reviewer-visible data leaves the current machine; it is not a judgment that the destination is untrusted. A private LAN endpoint remains external under this definition and is reported by `--dry-run`.

## Sensitive-Input Guard

Before any external reviewer is constructed, Quorum scans the complete reviewer-visible input: plan, commitments, tracked patch, untracked sections, and metadata. Unknown reviewer boundaries are rejected earlier as configuration errors.

The built-in scanner is a conservative warning gate for common key and credential shapes. It is not marketed as a replacement for a dedicated secret scanner.

The v0.7 warning classes are `private-key-block`, `aws-access-key`, `slack-token`, `openai-style-secret`, `github-token`, `bearer-authorization`, and `sensitive-assignment` for variable names containing `API_KEY`, `SECRET`, `TOKEN`, or `PASSWORD`. Tests use synthetic fixtures for every class and negative fixtures for placeholders, documentation examples, and short dummy values.

- Likely secrets plus any external reviewer require `--allow-secret-looking-input`.
- Captured untracked content plus any external reviewer requires `--allow-untracked-external`.
- Local-only runs continue with a warning.
- Debug and dry-run output report only warning classes and counts, never matched values.

Successful diff runs persist sensitive artifacts locally under `.krystal-quorum/reviews`. Documentation must warn users not to commit or casually upload those artifacts.

When writing artifacts inside a Git repository, Quorum checks whether `.krystal-quorum/` is ignored. If not, it prints a warning with the exact ignore entry to add. It does not silently edit the user's root `.gitignore` or `.git/info/exclude`.

## Diff Reviewer Contract

Diff reviewers use a separate strict output model rather than overloading the plan-review schema.

```json
{
  "verdict": "REVISE",
  "confidence": 0.84,
  "commitment_coverage": [
    {
      "commitment_id": "AC-1",
      "status": "PARTIAL",
      "claim": "The success path exists but the documented failure exit code is missing.",
      "evidence": "src/krystal_quorum/cli.py:214",
      "path": "src/krystal_quorum/cli.py",
      "line_start": 214
    }
  ],
  "scope_findings": [
    {
      "category": "dependency",
      "risk": "high",
      "claim": "The diff adds a production dependency not named in the approved plan.",
      "evidence": "pyproject.toml:24",
      "path": "pyproject.toml",
      "line_start": 24
    }
  ],
  "blocking_issues": [],
  "suggestions": [],
  "per_clause": {
    "scope.alignment": "SATISFIED",
    "tests.coverage": "UNSATISFIED",
    "security.alignment": "N/A",
    "dependencies.alignment": "N/A",
    "rollback.implemented": "UNCLEAR",
    "observability.implemented": "N/A"
  }
}
```

Coverage statuses are:

- `IMPLEMENTED`
- `PARTIAL`
- `MISSING`
- `NOT_EVIDENT`
- `N/A`

Reviewers must assess every commitment ID exactly once. Unknown, duplicate, or missing IDs make the response unparseable and trigger the existing one-shot parse retry.

Evidence paths must identify changed files when the claim points to present code. `path` and `line_start` may be null for missing or not-evident commitments because absence has no truthful code location. Line numbers may also be null for binary, submodule, or deleted-file evidence.

`scope_findings` is always present and uses an empty array when there is no unplanned scope. Its risk is `low`, `medium`, or `high`. High-risk categories are authentication or authorization, payments, credential handling, destructive data operations, schema migrations, production dependencies, and deployment configuration.

## Diff Reconciliation

Plan reconciliation remains unchanged. Diff reconciliation uses commitment IDs and structured evidence before free-text issue clustering.

- Agreement from at least two distinct reviewer IDs on the same commitment is corroborated.
- Family diversity remains separately reported and can be enforced with `--require-diversity`.
- Corroborated `MISSING` commitments or corroborated high-risk `scope_findings` produce `BLOCK`.
- Corroborated `PARTIAL` or `NOT_EVIDENT` commitments produce `REVISE`.
- Singleton blockers, singleton missing claims, and contradictions produce `REVISE` and human triage, not `BLOCK`.
- One reviewer cannot independently produce a merged diff verdict of `BLOCK`.
- Quorum collapse produces `REVISE` with explicit abstention diagnostics.
- `APPROVE` requires no missing, partial, or not-evident required commitments and no unresolved scope blocker.

Self-reported reviewer confidence remains visible only in per-reviewer artifacts. Diff results do not manufacture a scalar system-confidence number. They report usable reviewer count, distinct family count, commitment agreement ratio, contradiction count, quorum health, and plan provenance directly.

## Diff Result Schema

Diff runs use `krystal-quorum.diff.v1`; existing plan runs remain on their current schema.

The top-level JSON result has this shape:

```json
{
  "schema_version": "krystal-quorum.diff.v1",
  "review_kind": "diff",
  "verdict": "APPROVE",
  "plan_provenance": "verified_receipt",
  "plan": {
    "path": "docs/plans/change.md",
    "sha256": "...",
    "approval_sha256": "..."
  },
  "git": {
    "base_ref": "HEAD",
    "base_sha": "...",
    "head_ref": null,
    "head_sha": "...",
    "merge_base_sha": null,
    "working_tree": true
  },
  "diff": {
    "sha256": "...",
    "changed_files": [
      {
        "status": "M",
        "path": "src/krystal_quorum/cli.py",
        "old_path": null
      }
    ]
  },
  "review_input_sha256": "...",
  "quorum": {
    "health": "healthy",
    "usable_reviewers": 2,
    "total_reviewers": 2,
    "distinct_families": 2,
    "agreement_ratio": 1.0,
    "contradiction_count": 0
  },
  "reviewers_used": ["ollama:qwen2.5:14b", "command:local-codex"],
  "coverage": [
    {
      "commitment_id": "AC-1",
      "status": "IMPLEMENTED",
      "corroborated": true,
      "reviewers": ["ollama:qwen2.5:14b", "command:local-codex"],
      "evidence": ["src/krystal_quorum/cli.py:214"]
    }
  ],
  "scope_findings": [],
  "unresolved_for_human": [],
  "output_dir": ".krystal-quorum/reviews/change_..."
}
```

`approval_sha256` is null in standalone mode. `head_ref`, `head_sha`, and `merge_base_sha` follow the selected working-tree or committed-ref mode. The exact Pydantic models use strict enums and nullable fields matching this public JSON shape.

The result records:

- plan provenance
- plan SHA256
- approval receipt SHA256, when present
- diff SHA256
- complete review-input SHA256
- base, head, and merge-base SHAs
- changed files
- commitment coverage aggregation
- reviewer reconciliation
- quorum health and diversity
- artifact directory

This avoids assigning a combined plan-and-diff hash to the existing `plan_sha256` field.

## Artifacts

A successful diff gate, including a deterministic empty-diff `REVISE`, writes:

```text
manifest.json
plan_input.md
plan_input.sha256
approval.json                 # verified mode only
diff_input.patch
diff_input.sha256
changed_files.json
review_input.md
review_input.sha256
coverage.json
reconciled.json
summary.md
round1/<reviewer>.json         # when reviewer execution occurred
round2/<reviewer>.json        # when enabled
```

`manifest.json` contains schema and tool versions, provenance, resolved refs, hashes, reviewer IDs, families, boundaries, and hashes of persisted artifacts. It does not duplicate plan or diff contents.

`summary.md` renders, in order: verdict and provenance; resolved baseline and head; quorum health and diversity; a commitment table with ID, aggregate status, corroboration, and bounded evidence; unplanned scope findings; abstentions and contradictions; human triage; and artifact paths. Missing or null evidence locations render as `not present in diff`, not as invented filenames.

Preflight failures and `--dry-run` do not create a run directory. Once reviewer execution starts, Quorum persists the run even when the final verdict or reviewer runtime fails.

## GitHub Action

The composite Action gains `mode: review|diff` while preserving review mode defaults.

Diff-mode inputs include:

- `plan`
- `base` and optional `head` for standalone mode
- `repo`
- `max-diff-chars`
- `max-review-chars`
- `context-lines`
- `include-untracked`
- `allow-untracked-external`
- `allow-secret-looking-input`
- existing reviewer, round 2, diversity, config, and API inputs

The documented pull-request example uses exact event SHAs and full history:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0

- id: quorum
  uses: KrystalUnity/krystal-quorum@v0.7.0
  with:
    mode: diff
    plan: docs/plans/change.md
    base: ${{ github.event.pull_request.base.sha }}
    head: ${{ github.event.pull_request.head.sha }}
    reviewers: openai:gpt-4.1,openai:o4-mini
    include-untracked: "false"
    package-spec: krystal-quorum==0.7.0
```

Action diff mode is intentionally standalone in v0.7 and always reports `plan_provenance: unverified_reference`. It does not accept approval receipts because verified mode requires the sibling plan-review result, which may contain sensitive reviewer artifacts and must not be committed merely to satisfy CI. Portable verified CI provenance is a separate future attestation design.

Before returning Quorum's exit code, the Action always:

1. emits the configured artifact-root `output-dir`
2. emits run-specific `latest-output-dir` and `summary-path` when reviewer execution or a deterministic verdict created a run; both are empty on preflight failure
3. appends `summary.md` to `$GITHUB_STEP_SUMMARY` when a run exists, otherwise appends a concise preflight-failure note without inventing an artifact path
4. preserves `REVISE`, `BLOCK`, and runtime exit codes

The Action does not post pull-request comments or request write permissions in v0.7.

## Hosted Boundary

Public hosted diff review is excluded from v0.7. `hosted:*` passed to `diff` exits `3` with a clear message before HTTP.

The later hosted API must accept separate structured fields rather than placing a combined document in `plan_markdown`:

- `review_kind`
- `plan_markdown`
- `approval_receipt`
- `diff_patch`
- `diff_metadata`
- `commitments`
- client version and source

Hosted support may be documented only after staging and production evidence proves routing, size limits, retention, billing, failure/no-charge behavior, and artifact persistence. That work is a separate server design and release gate.

## Error Handling

Preflight failures use exit code `3` and the stable prefix `krystal-quorum error:`. Debug details use `krystal-quorum debug:` and are bounded to command names, redacted arguments, exit codes, and at most 500 characters of stderr.

Debug output never contains plan text, diff text, matched secret values, API keys, authorization headers, complete endpoint credentials, or raw reviewer payloads.

Review verdicts retain the existing contract:

- `0`: `APPROVE`
- `1`: `REVISE`
- `2`: `BLOCK`
- `3`: runtime, configuration, provenance, or preflight error

## Compatibility

- Existing `review`, `demo`, and `init` commands remain compatible.
- Existing plan JSON, artifacts, and `ReconciledVerdict` fields do not gain diff-only meanings.
- Existing reviewer transports are reused, but diff responses are parsed into a separate strict model.
- `mock` remains a deterministic smoke test and must never be presented as AI review.
- The legacy consensus matcher remains available only for plan review. Diff commitment reconciliation has no legacy fallback.

## Implementation Map

The implementation plan may refine filenames, but ownership stays separated along these boundaries:

- `commitments.py`: heading normalization, alias table, commitment IDs, extraction, and validation
- `approval.py`: repository binding, canonical receipt models, hashes, revalidation, and receipt loading
- `diffing.py`: Git ref resolution, safe subprocess calls, NUL-safe status parsing, untracked handling, and snapshot hashes
- `reviewer_specs.py`: one normalized reviewer parser, family metadata, endpoint parsing, and data boundaries
- `diff_models.py`: strict reviewer, coverage, scope-finding, manifest, and public-result models
- `diff_reconcile.py`: commitment aggregation, scope reconciliation, quorum health, and diff verdicts
- existing reviewer adapters: transport reuse with an explicit diff prompt and diff-output parser
- `cli.py`: bound-review options, `diff`, dry-run, preflight ordering, and exit behavior
- `persist.py` and `formatting.py`: receipt, diff artifacts, human summary, JSON, and pretty output
- root and nested `action.yml`: diff inputs, preserved outputs, and `$GITHUB_STEP_SUMMARY`
- agent packs and the Copilot target: project-local instruction templates, the shared workflow, and the future `.github/copilot-instructions.md` integration

No module may both execute reviewer transports and decide Git provenance. That boundary keeps network behavior out of preflight and makes fail-closed tests reliable.

## Test Strategy

### Receipt And Commitments

- canonical receipt serialization and hash
- receipt emitted only for eligible `APPROVE` runs
- bound review requires a tracked plan and clean baseline
- concurrent plan, `HEAD`, or worktree changes prevent receipt creation after review
- bound receipt creation succeeds when the configured artifact directory is not yet Git-ignored
- revalidation occurs before artifact persistence and excludes only the configured artifact directory
- missing or hash-mismatched sibling `reconciled.json` rejects verified mode
- altered plan, commitment, receipt, or baseline rejection
- duplicate or category-mismatched explicit commitment IDs
- every heading alias, exact-match rejection, descendant-heading grouping, section-closing levels, nested continuation lines, CRLF, and non-ASCII text
- no required commitment in any recognized category fails preflight before reviewer construction

### Git Capture

- verified exact-base and ancestry behavior
- standalone merge-base behavior
- committed, staged, unstaged, staged-plus-unstaged, and untracked changes
- adds, deletes, renames, copy-as-add behavior, spaces, tabs, newlines, and non-ASCII paths
- NUL-delimited parsing
- binary, symlink, submodule, unreadable, FIFO, and out-of-root handling
- `--no-ext-diff`, `--no-textconv`, and no shell execution
- deterministic hashes and line-ending normalization
- empty and oversized diff behavior

### Boundaries And Safety

- one normalized reviewer parser drives both metadata and construction
- loopback IPv4, loopback IPv6, localhost, LAN, and external endpoints
- cloud-tagged Ollama models
- local and external command reviewers, plus fail-closed rejection of unknown boundaries
- complete-input secret scanning
- untracked and likely-secret opt-ins happen before client construction
- dry-run invokes only bounded Git subprocesses and performs no reviewer command, agent CLI, or network execution

### Reviewer And Reconciliation

- complete commitment coverage required from every reviewer
- structured unplanned-scope findings and high-risk category handling
- end-to-end golden flow from approved receipt through diff capture to reconciled coverage and artifacts
- retry on malformed diff output
- corroborated, singleton, contradictory, and abstained findings
- one reviewer cannot create merged `BLOCK`
- explicit provenance, quorum-health, and agreement metrics without aggregate confidence
- round 2 preserves commitment IDs and peer evidence

### CLI, Artifacts, And Action

- plan mode regression suite remains unchanged
- agent packs install the shared workflow and supported target instructions, including the Copilot target
- diff JSON and pretty output
- every persisted artifact and manifest hash
- no artifacts for preflight or dry-run
- Action uses exact PR SHAs and full-history guidance
- Action diff mode is explicitly standalone and unverified in v0.7
- failing Action runs still emit outputs and append the step summary
- module-entry smoke test
- Ubuntu and Windows CI coverage on Python 3.11 and 3.12, plus macOS on Python 3.12
- package build and `twine check`

## Acceptance Criteria

- A repository-bound approved plan with at least one required commitment produces an unsigned `approval.json` with the exact plan hash, baseline SHA, commitments, reviewer metadata, and reconciled hash.
- Receipt revalidation cannot be invalidated by Quorum's own artifact writes.
- Editing the plan or rebasing away from the approved baseline causes verified diff mode to exit `3` before reviewer construction.
- Standalone mode remains usable and labels its provenance as unverified.
- `--dry-run` constructs no reviewer clients, invokes no reviewer commands or agent CLIs, makes no network calls, and creates no artifacts; bounded Git subprocesses still run.
- Duplicate or category-mismatched explicit commitment IDs fail preflight in bound and standalone modes.
- Diff output contains a commitment coverage matrix with evidence paths.
- Present-code evidence preserves changed-file paths and line numbers; missing or non-text evidence uses explicit null locations rather than invented lines.
- One reviewer cannot independently produce a merged diff `BLOCK`.
- The result separately records plan, diff, complete-input, and receipt hashes.
- Git path parsing is NUL-safe and diff generation disables external diff and text-conversion execution.
- The entire reviewer-visible input is checked before external reviewers are called, and unknown reviewer boundaries are rejected before execution.
- Successful diff runs always persist auditable artifacts; preflight and dry-run do not.
- The GitHub Action exposes a run-specific summary for `REVISE`, `BLOCK`, abstention, and post-start runtime failures; preflight failures expose only the artifact root and a concise step-summary error.
- The v0.7 GitHub Action does not accept approval receipts or imply verified provenance.
- Existing v0.6 plan-review behavior remains compatible.
- Agent-native execution provides the zero-command day-to-day path after one-time install and init; CI remains the hard enforcement boundary.
- Hosted diff review is absent from public v0.7 examples and fails closed in the client.

## Rollout

1. Implement and test repository-bound plan receipts and commitment extraction.
2. Implement local diff capture, diff reviewer contracts, reconciliation, and artifacts.
3. Exercise the complete path with local command reviewers and local Ollama.
4. Add standalone API reviewers and the GitHub Action surface.
5. Add agent packs, including the Copilot target, and verify the one-time-init zero-command workflow.
6. Release the OSS feature as v0.7.0 after Windows/Linux verification and a diverse reviewer quorum approves the implementation evidence.
7. Design and verify the structured hosted API separately before enabling hosted diff review.

## Rollback

The feature is additive. If diff mode proves unsafe or noisy before release, remove the `diff` command, bound-receipt options, diff models, Action inputs, and documentation while leaving all v0.6 plan-review behavior intact.

If a published v0.7 release is faulty, yank the package version, mark the GitHub release and Marketplace listing as withdrawn, and return all examples and recommended refs to v0.6.7 until a fixed patch is verified. Published `v0.7.0` Git and Action tags are immutable and are never retargeted to different code; the advisory must tell pinned users to move to the last good tag or the corrected patch. Publish that patch only after rebuilding from a clean commit and rerunning the full verification suite.
