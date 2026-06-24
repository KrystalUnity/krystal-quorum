from __future__ import annotations

import json

from krystal_quorum.models import ReviewerOutput, Verdict


def round1_prompt(reviewer_id: str, plan_text: str) -> str:
    return f"""You are {reviewer_id}, reviewing an AI coding plan before implementation.

Return JSON only inside <json>...</json> tags. Use exactly this schema. Do not add extra keys.

<json>
{{
  "verdict": "REVISE",
  "confidence": 0.8,
  "blocking_issues": [
    {{
      "id": "B1",
      "section": "Acceptance",
      "claim": "Specific blocking problem.",
      "evidence": "Exact plan text or omission that proves the claim."
    }}
  ],
  "suggestions": [
    {{
      "id": "S1",
      "section": "Tests",
      "claim": "Specific non-blocking improvement.",
      "rationale": "Why this improves safety or verifiability."
    }}
  ],
  "per_clause": {{
    "acceptance.criteria": "UNSATISFIED",
    "rollback.plan": "UNCLEAR",
    "tests.verification": "SATISFIED",
    "safety.assumptions": "N/A",
    "security.risk": "UNCLEAR",
    "dependencies.scope": "N/A",
    "observability.plan": "N/A"
  }}
}}
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
"""


def round2_prompt(
    reviewer_id: str,
    plan_text: str,
    round1_outputs: list[ReviewerOutput],
) -> str:
    peer_findings = [
        {
            "reviewer": output.reviewer,
            "verdict": output.verdict.value,
            "blocking_issues": [issue.model_dump(mode="json") for issue in output.blocking_issues],
            "suggestions": [item.model_dump(mode="json") for item in output.suggestions],
        }
        for output in round1_outputs
        if output.verdict != Verdict.ABSTAIN
    ]
    peer_findings_json = json.dumps(peer_findings, indent=2)
    return f"""You are {reviewer_id}, performing Round 2 cross-audit.

Review peer findings, agree or refute them using the plan text, and return a fresh strict JSON verdict.

PEER FINDINGS:
{peer_findings_json}

{round1_prompt(reviewer_id, plan_text)}
"""
