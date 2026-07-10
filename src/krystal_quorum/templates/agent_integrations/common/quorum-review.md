# Krystal Quorum Agent Review Gate

Use Krystal Quorum automatically before an AI coding agent starts non-trivial
implementation work. This is policy automation: it guides agent behavior but
does not enforce it. The GitHub Action is the hard enforcement boundary.

## When To Run

Run Quorum when a task has a markdown plan, touches user-visible behavior,
changes data or auth flows, lacks clear acceptance criteria, or would benefit
from independent review before editing code.

## Plan Shape

Write or locate a markdown plan with recognized commitment sections:

- goal and non-goals
- expected files or modules
- implementation steps
- acceptance criteria
- rollback plan
- verification commands
- security, dependency, observability, and operational risks

## Two-Gate Workflow

1. Use the project's configured real reviewers. If no reviewer profile exists,
   ask the human once which real reviewer profile to use; do not silently fall
   back to a different provider.
2. Before any code edit, run the bound plan gate from the repository root:

```bash
krystal-quorum review <plan.md> \
  --bind-repo . \
  --config <reviewer-config> \
  --reviewers <configured-reviewers> \
  --round2 \
  --format pretty
```

3. Handle the bound verdict before implementation:
   - `APPROVE`: retain the emitted `approval.json` path and implement only the
     approved scope.
   - `REVISE`: revise the plan and rerun this gate until `APPROVE`, or return
     the unresolved choice to the human.
   - `BLOCK`: return the blockers to the human for triage; do not edit code.
   - `ABSTAIN`: return the reviewer diagnostics to the human and configure
     usable real reviewers.
4. Run normal tests for the approved implementation.
5. Run the verified diff gate with the same reviewer profile:

```bash
krystal-quorum diff \
  --plan <plan.md> \
  --approval <approval.json> \
  --repo . \
  --config <reviewer-config> \
  --reviewers <configured-reviewers> \
  --round2 \
  --format pretty
```

6. Handle `REVISE` or `BLOCK` from the diff gate by remediating and rerunning,
   or present unresolved human triage. Report both gate verdicts and both
   artifact paths, including the retained approval path.

Use `mock` only for installation smoke tests. For real review, use diverse
local command, Ollama, or API reviewers.

Do not automatically commit, push, or deploy; do not hide a failed gate or
claim that CI enforcement ran locally.

## Verdict Handling

Always inspect `summary.md` for human triage. Use `reconciled.json` for
automation. Quorum is not permission to deploy, delete data, send external
messages, expand scope, or bypass user approval.
