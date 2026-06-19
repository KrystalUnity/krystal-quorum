from __future__ import annotations

from krystal_quorum.models import ReviewerOutput, Verdict


def round1_prompt(reviewer_id: str, plan_text: str) -> str:
    return f"""You are {reviewer_id}, reviewing an AI coding plan before implementation.

Return JSON only inside <json>...</json> tags with this shape:

<json>
{{
  "verdict": "APPROVE",
  "confidence": 0.8,
  "blocking_issues": [],
  "suggestions": [],
  "per_clause": {{}}
}}
</json>

Use verdict APPROVE, REVISE, or BLOCK.
Flag missing acceptance criteria, contradictions, unsafe assumptions, rollback gaps, and test gaps.

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
    return f"""You are {reviewer_id}, performing Round 2 cross-audit.

Review peer findings, agree or refute them using the plan text, and return a fresh strict JSON verdict.

PEER FINDINGS:
{peer_findings}

{round1_prompt(reviewer_id, plan_text)}
"""
