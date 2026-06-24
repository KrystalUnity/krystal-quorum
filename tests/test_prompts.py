import json

from krystal_quorum.models import ReviewerOutput, Verdict
from krystal_quorum.prompts import round1_prompt, round2_prompt


def test_round1_prompt_specifies_issue_suggestion_and_clause_schema():
    prompt = round1_prompt("command:local", "plan text")

    assert '"blocking_issues": [' in prompt
    assert '"id": "B1"' in prompt
    assert '"claim": "Specific blocking problem."' in prompt
    assert '"evidence": "Exact plan text or omission that proves the claim."' in prompt
    assert '"suggestions": [' in prompt
    assert '"rationale": "Why this improves safety or verifiability."' in prompt
    assert '"per_clause": {' in prompt
    assert '"tests.verification": "SATISFIED"' in prompt
    assert '"security.risk": "UNCLEAR"' in prompt
    assert '"dependencies.scope": "N/A"' in prompt
    assert '"observability.plan": "N/A"' in prompt
    assert "Use these exact per_clause keys when judging plan coverage." in prompt
    assert "Only use per_clause values SATISFIED, UNSATISFIED, UNCLEAR, or N/A." in prompt
    assert "security, dependency, and observability gaps" in prompt


def test_round2_prompt_embeds_peer_findings_as_json():
    output = ReviewerOutput(
        reviewer="peer",
        round=1,
        verdict=Verdict.REVISE,
        confidence=0.8,
        blocking_issues=[],
        suggestions=[],
        per_clause={},
        raw_response="{}",
        elapsed_seconds=0.1,
    )

    prompt = round2_prompt("reviewer", "plan text", [output])

    peer_json = prompt.split("PEER FINDINGS:\n", 1)[1].split("\n\nYou are reviewer", 1)[0]
    parsed = json.loads(peer_json)
    assert parsed == [
        {
            "reviewer": "peer",
            "verdict": "REVISE",
            "blocking_issues": [],
            "suggestions": [],
        }
    ]
    assert "'verdict':" not in peer_json
