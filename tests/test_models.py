import pytest
from pydantic import ValidationError

from krystal_quorum.models import ClauseStatus, ReviewerOutput, Verdict


def test_reviewer_output_accepts_valid_payload():
    output = ReviewerOutput(
        reviewer="mock",
        round=1,
        verdict=Verdict.REVISE,
        confidence=0.75,
        blocking_issues=[],
        suggestions=[],
        per_clause={"acceptance.1": ClauseStatus.UNSATISFIED},
        raw_response="{}",
        elapsed_seconds=0.1,
    )

    assert output.verdict == Verdict.REVISE


def test_reviewer_output_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ReviewerOutput(
            reviewer="mock",
            round=1,
            verdict="APPROVE",
            confidence=0.5,
            blocking_issues=[],
            suggestions=[],
            per_clause={},
            raw_response="{}",
            elapsed_seconds=0.1,
            unexpected=True,
        )
