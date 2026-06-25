# Demo

Krystal Quorum can be tried without API keys by using the deterministic `mock` reviewer.

![Animated terminal card](assets/quorum-demo.svg)

## Weak Plan

```bash
krystal-quorum review examples/bad-plan.md --reviewers mock --format pretty
```

Expected result:

```text
VERDICT: REVISE | Confidence: 0.77
Reviewers: mock
Diversity: ok
Singleton Blockers (1)
- [Acceptance] The plan does not include explicit acceptance criteria.
Artifacts: .krystal-quorum/reviews/...
```

The mock reviewer flags the missing acceptance criteria and exits with code `1`.

## Fixed Plan

```bash
krystal-quorum review examples/good-plan.md --reviewers mock --format pretty
```

Expected result:

```text
VERDICT: APPROVE | Confidence: 0.90
Reviewers: mock
Diversity: ok
Shared Blockers (0)
- none
Artifacts: .krystal-quorum/reviews/...
```

The fixed plan includes acceptance criteria, so the mock reviewer exits with code `0`.

## Agent Integration

Install project-local prompts or skills:

```bash
krystal-quorum init --target claude-code
krystal-quorum init --target codex
krystal-quorum init --target hermes
krystal-quorum init --target claw
krystal-quorum init --target openclaw
krystal-quorum init --target opencode
krystal-quorum init --target all
```

Use `mock` only to prove the flow. Real plan review should use diverse local, API, or command reviewers.
