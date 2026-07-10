---
name: krystal-quorum-openclaw-review
description: Automatically run Krystal Quorum's two-gate workflow before non-trivial OpenClaw implementation dispatch.
---

# Krystal Quorum Review

For every non-trivial implementation task, automatically read and follow
`.krystal-quorum/agents/quorum-review.md` before editing code or dispatching a
worker. Keep the bound plan approval artifact and use it for the verified
implementation-diff review.

The shared workflow is policy automation, not enforcement. The GitHub Action
is the hard enforcement boundary. Do not automatically commit, push, or deploy;
report both gate verdicts and artifact paths for human control.
