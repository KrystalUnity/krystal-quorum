# Agent Handoff Plan

## Goal

Add a small `last_reviewed_at` field to the plan review summary so downstream agents can display when Quorum produced the verdict.

## Non-goals

- Do not change the reviewer JSON contract.
- Do not change verdict reconciliation.
- Do not migrate existing artifacts.

## Files Expected To Change

- `src/krystal_quorum/persist.py`
- `tests/test_persist.py`
- `README.md`

## Implementation Steps

1. Add an ISO timestamp to the persisted `summary.md` heading.
2. Keep `reconciled.json` unchanged for schema compatibility.
3. Update the persistence test to assert the timestamp line exists.
4. Update the README artifact description.

## Acceptance Criteria

- New review runs write a readable `last reviewed` line in `summary.md`.
- Existing JSON consumers continue to parse `reconciled.json`.
- Tests pass on a clean checkout.

## Rollback Plan

Revert the summary formatting change only; no artifact schema rollback is needed.

## Verification

Run:

```bash
python -m pytest tests/test_persist.py -q
python -m pytest -q
```

## Risks And Assumptions

The timestamp is presentation-only. Automation should continue using `reconciled.json`.
