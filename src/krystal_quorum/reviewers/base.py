from __future__ import annotations

import json
import re
import time
from typing import Any, Protocol

from pydantic import ValidationError

from krystal_quorum.models import ReviewIssue, ReviewerOutput, Verdict


class ReviewerProtocol(Protocol):
    id: str

    async def review_round1(self, plan_text: str, *, timeout_s: int) -> ReviewerOutput: ...

    async def review_round2(
        self, plan_text: str, round1_outputs: list[ReviewerOutput], *, timeout_s: int
    ) -> ReviewerOutput: ...


def fallback_output(
    reviewer: str,
    round_number: int,
    claim: str,
    evidence: str = "",
    raw_response: str = "",
    elapsed_seconds: float = 0.0,
    retries: int = 0,
) -> ReviewerOutput:
    return ReviewerOutput(
        reviewer=reviewer,
        round=round_number,  # type: ignore[arg-type]
        verdict=Verdict.ABSTAIN,
        confidence=0.0,
        blocking_issues=[
            ReviewIssue(
                id="B0",
                section="runtime",
                claim=f"reviewer abstained: {claim}",
                evidence=evidence[:500],
            )
        ],
        suggestions=[],
        per_clause={},
        raw_response=raw_response,
        elapsed_seconds=elapsed_seconds,
        retries=retries,
    )


def extract_json(raw: str) -> dict[str, Any] | None:
    match = re.search(r"<json>\s*(\{.*?\})\s*</json>", raw, flags=re.DOTALL | re.IGNORECASE)
    candidate = match.group(1) if match else raw.strip()
    if not candidate.startswith("{"):
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_reviewer_output(
    reviewer: str,
    round_number: int,
    raw_response: str,
    elapsed_seconds: float,
    retries: int,
) -> ReviewerOutput:
    try:
        payload = extract_json(raw_response)
        if payload is None:
            raise ValueError("reviewer output unparseable")
        payload.update(
            {
                "reviewer": reviewer,
                "round": round_number,
                "raw_response": raw_response,
                "elapsed_seconds": elapsed_seconds,
                "retries": retries,
            }
        )
        return ReviewerOutput.model_validate(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        return fallback_output(
            reviewer,
            round_number,
            claim="reviewer output unparseable",
            evidence=raw_response[:500] or str(exc),
            raw_response=raw_response,
            elapsed_seconds=elapsed_seconds,
            retries=retries,
        )


def elapsed_since(start: float) -> float:
    return round(time.monotonic() - start, 3)
