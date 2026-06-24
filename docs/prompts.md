# Reviewer Prompt Contract

Krystal Quorum asks every reviewer for strict JSON inside `<json>...</json>` tags. The current Round 1 prompt is intentionally transparent so users can inspect the rubric before trusting the tool.

## Round 1 Prompt Shape

```text
You are {reviewer_id}, reviewing an AI coding plan before implementation.

Return JSON only inside <json>...</json> tags. Use exactly this schema. Do not add extra keys.

<json>
{
  "verdict": "REVISE",
  "confidence": 0.8,
  "blocking_issues": [
    {
      "id": "B1",
      "section": "Acceptance",
      "claim": "Specific blocking problem.",
      "evidence": "Exact plan text or omission that proves the claim."
    }
  ],
  "suggestions": [
    {
      "id": "S1",
      "section": "Tests",
      "claim": "Specific non-blocking improvement.",
      "rationale": "Why this improves safety or verifiability."
    }
  ],
  "per_clause": {
    "acceptance.criteria": "UNSATISFIED",
    "rollback.plan": "UNCLEAR",
    "tests.verification": "SATISFIED",
    "safety.assumptions": "N/A",
    "security.risk": "UNCLEAR",
    "dependencies.scope": "N/A",
    "observability.plan": "N/A"
  }
}
</json>

Use verdict APPROVE, REVISE, or BLOCK.
Use these exact per_clause keys when judging plan coverage.
Only use per_clause values SATISFIED, UNSATISFIED, UNCLEAR, or N/A.
Use an empty array when there are no blocking issues or suggestions.
Flag missing acceptance criteria, contradictions, unsafe assumptions, rollback gaps,
test gaps, security, dependency, and observability gaps.

PLAN:
---
{plan_text}
---
```

## Round 2

When `--round2` is enabled, Quorum serializes non-abstained peer findings as JSON and asks each reviewer to cross-audit them against the same plan text. Reviewers return a fresh strict JSON verdict after considering peer findings.

## Parser Behavior

- Tagged `<json>...</json>` payloads are preferred.
- Untagged responses are scanned for complete reviewer-shaped JSON objects.
- Malformed reviewer output gets one JSON-only retry.
- Transient HTTP failures are retried before the reviewer is marked `ABSTAIN`.
- Reasoning-only fields are parsed only when they contain explicit JSON tags.
