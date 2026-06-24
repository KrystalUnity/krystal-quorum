import pytest

from krystal_quorum.models import Verdict
from krystal_quorum.reviewers.base import extract_json, parse_reviewer_output
from krystal_quorum.reviewers.mock import MockReviewer


def test_parse_reviewer_json_from_tags():
    raw = (
        '<json>{"verdict":"APPROVE","confidence":0.9,'
        '"blocking_issues":[],"suggestions":[],"per_clause":{}}</json>'
    )

    output = parse_reviewer_output("mock", 1, raw, elapsed_seconds=0.2, retries=0)

    assert output.verdict == Verdict.APPROVE


def test_parse_reviewer_json_from_noisy_stdout():
    raw = (
        "booting local reviewer...\n"
        '{"verdict":"REVISE","confidence":0.7,'
        '"blocking_issues":[],"suggestions":[],"per_clause":{}}\n'
        "resume this session with: reviewer --continue abc123\n"
    )

    output = parse_reviewer_output("command:local", 1, raw, elapsed_seconds=0.2, retries=0)

    assert output.verdict == Verdict.REVISE


def test_parse_reviewer_output_tolerates_common_issue_shape_drift():
    raw = (
        '{"verdict":"BLOCK","confidence":0.7,'
        '"summary":"The review found one test blocker.",'
        '"blocking_issues":[{"id":"B1","section":"Tests",'
        '"description":"The plan does not name a verification command.",'
        '"evidence":"No pytest or smoke command is listed.","severity":"high"}],'
        '"suggestions":[{"id":"S1","section":"Tests",'
        '"description":"Add a focused regression test.",'
        '"reason":"This makes the plan verifiable.","priority":"medium"}],'
        '"per_clause":{"tests.verification":"UNSATISFIED"}}'
    )

    output = parse_reviewer_output("command:local", 1, raw, elapsed_seconds=0.2, retries=0)

    assert output.verdict == Verdict.BLOCK
    assert output.blocking_issues[0].claim == "The plan does not name a verification command."
    assert output.suggestions[0].rationale == "This makes the plan verifiable."


def test_extract_json_prefers_last_complete_reviewer_object_without_tags():
    schema_echo = (
        '{"verdict":"APPROVE","confidence":0.1,'
        '"blocking_issues":[],"suggestions":[],"per_clause":{}}'
    )
    real_answer = (
        '{"verdict":"REVISE","confidence":0.8,'
        '"blocking_issues":[{"id":"B1","section":"Tests",'
        '"claim":"Missing verification","evidence":"No tests listed"}],'
        '"suggestions":[],"per_clause":{}}'
    )

    payload = extract_json(f"Example:\n{schema_echo}\nFinal:\n{real_answer}")

    assert payload is not None
    assert payload["verdict"] == "REVISE"
    assert payload["blocking_issues"][0]["claim"] == "Missing verification"


def test_extract_json_still_prefers_tagged_payload():
    untagged_real_answer = (
        '{"verdict":"BLOCK","confidence":0.8,'
        '"blocking_issues":[{"id":"B1","section":"Safety",'
        '"claim":"Unsafe","evidence":"Deletes data"}],'
        '"suggestions":[],"per_clause":{}}'
    )
    tagged = (
        '<json>{"verdict":"APPROVE","confidence":0.9,'
        '"blocking_issues":[],"suggestions":[],"per_clause":{}}</json>'
    )

    payload = extract_json(f"{tagged}\n{untagged_real_answer}")

    assert payload is not None
    assert payload["verdict"] == "APPROVE"


def test_unparseable_output_abstains():
    output = parse_reviewer_output("mock", 1, "not json", elapsed_seconds=0.1, retries=0)

    assert output.verdict == Verdict.ABSTAIN
    assert output.blocking_issues[0].id == "B0"


@pytest.mark.asyncio
async def test_mock_reviewer_flags_missing_acceptance():
    reviewer = MockReviewer()

    output = await reviewer.review_round1("Build a CLI with no success criteria.", timeout_s=1)

    assert output.verdict == Verdict.REVISE
    assert output.blocking_issues
