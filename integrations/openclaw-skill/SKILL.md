---
name: krystal-quorum-openclaw-review
description: Add a Krystal Quorum pre-dispatch review gate to OpenClaw-style agent workflows.
---

# Krystal Quorum OpenClaw Review

Before an agent implements a substantial plan:

1. Save the plan as markdown.
2. Run `krystal-quorum review <plan.md> --reviewers <configured-reviewers>`.
3. Inspect `summary.md` and `reconciled.json`.
4. Revise missing acceptance criteria, contradictions, rollback gaps, and test gaps.
5. Continue only after user review when the verdict is `REVISE` or `BLOCK`.

Krystal Quorum is a review step. It is not an agent runtime and does not run tools.
