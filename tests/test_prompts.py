from krystal_quorum.prompts import round1_prompt


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
    assert "Only use per_clause values SATISFIED, UNSATISFIED, UNCLEAR, or N/A." in prompt
