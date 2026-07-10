---
name: quorum-review
description: Automatically apply Krystal Quorum's verified two-gate workflow to non-trivial implementation work.
argument-hint: <plan.md> [reviewers]
---

# Krystal Quorum Two-Gate Review

For non-trivial implementation work, automatically read and follow
`.krystal-quorum/agents/quorum-review.md` before editing code. Treat the first
argument as the plan path and the optional second argument as the configured
reviewer list.

The shared workflow is policy automation, not enforcement. The GitHub Action
is the hard enforcement boundary. Do not automatically commit, push, or deploy;
report the plan-gate verdict, diff-gate verdict, and their artifact paths for
human control.
