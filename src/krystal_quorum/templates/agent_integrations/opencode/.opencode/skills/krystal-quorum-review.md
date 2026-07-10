# Krystal Quorum Review

For every non-trivial implementation task, automatically read and follow
`.krystal-quorum/agents/quorum-review.md` before editing code. Keep the bound
plan approval artifact and use it for the verified implementation-diff review.

The shared workflow is policy automation, not enforcement. The GitHub Action
is the hard enforcement boundary. Do not automatically commit, push, or deploy;
report both gate verdicts and artifact paths for human control.
