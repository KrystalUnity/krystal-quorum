import pytest

from krystal_quorum.models import Verdict
from krystal_quorum.reviewers.base import parse_reviewer_output
from krystal_quorum.reviewers.mock import MockReviewer


def test_parse_reviewer_json_from_tags():
    raw = (
        '<json>{"verdict":"APPROVE","confidence":0.9,'
        '"blocking_issues":[],"suggestions":[],"per_clause":{}}</json>'
    )

    output = parse_reviewer_output("mock", 1, raw, elapsed_seconds=0.2, retries=0)

    assert output.verdict == Verdict.APPROVE


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
