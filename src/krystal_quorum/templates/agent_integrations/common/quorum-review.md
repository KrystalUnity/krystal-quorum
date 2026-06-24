# Krystal Quorum Agent Review Gate

Use Krystal Quorum before an AI coding agent starts non-trivial implementation work.

## When To Run

Run Quorum when a task has a markdown plan, touches user-visible behavior, changes data or auth flows, lacks clear acceptance criteria, or would benefit from independent review before code is written.

## Plan Shape

Prefer a markdown plan with:

- goal and non-goals
- expected files or modules
- implementation steps
- acceptance criteria
- rollback plan
- verification commands
- security, dependency, observability, and operational risks

## Command

From the repository root:

```bash
krystal-quorum review <plan.md> --reviewers <reviewers> --round2 --format pretty
```

Use `mock` only for installation smoke tests. For real review, use diverse local, API, hosted, or command reviewers.

## Verdict Handling

- `APPROVE`: proceed with normal implementation and verification.
- `REVISE`: revise the plan, rerun Quorum, or ask the user before coding.
- `BLOCK`: stop implementation until blockers are triaged.
- `ABSTAIN`: inspect reviewer diagnostics and rerun with working reviewers.

Always inspect `summary.md` for human triage. Use `reconciled.json` for automation.

Quorum is a review gate. It is not permission to deploy, delete data, send external messages, expand scope, or bypass user approval.
