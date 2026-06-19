---
name: krystal-quorum-plan-review
description: Run Krystal Quorum before implementing non-trivial AI coding plans.
---

# Krystal Quorum Plan Review

Use this skill before implementing a non-trivial, high-risk, or underspecified coding task.

1. Write the proposed implementation plan to a markdown file.
2. Run `krystal-quorum review <plan.md>`.
3. Read the generated `summary.md`.
4. Treat reviewer findings as advisory signals, not approval or rejection by themselves.
5. Revise material issues before coding.
6. Ask the operator before implementation when the verdict is `REVISE` or `BLOCK`.

Do not use reviewer output as permission to deploy, migrate, delete, send messages, or expand scope.
