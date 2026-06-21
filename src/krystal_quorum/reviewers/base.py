from __future__ import annotations

import json
import re
import time
from typing import Any, Protocol

from pydantic import ValidationError

from krystal_quorum.models import ReviewIssue, ReviewerOutput, Verdict

ISSUE_ALIASES = {
    "claim": ("claim", "description", "problem", "issue", "summary"),
    "evidence": ("evidence", "details", "reason", "rationale"),
}
SUGGESTION_ALIASES = {
    "claim": ("claim", "description", "suggestion", "summary"),
    "rationale": ("rationale", "reason", "why", "evidence", "details"),
}
TOP_LEVEL_FIELDS = {"verdict", "confidence", "blocking_issues", "suggestions", "per_clause"}


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


def _json_object_candidates(raw: str) -> list[str]:
    candidates: list[str] = []
    start = raw.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(raw)):
            char = raw[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(raw[start : index + 1])
                    break
        start = raw.find("{", start + 1)
    return candidates


def _load_json_object(candidate: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(candidate.strip())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_json(raw: str) -> dict[str, Any] | None:
    match = re.search(r"<json>\s*(.*?)\s*</json>", raw, flags=re.DOTALL | re.IGNORECASE)
    direct_candidates = [match.group(1)] if match else [raw]
    for candidate in direct_candidates:
        parsed = _load_json_object(candidate)
        if parsed is not None:
            return parsed
        for balanced in _json_object_candidates(candidate):
            parsed = _load_json_object(balanced)
            if parsed is not None:
                return parsed
    return None


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_issue(item: Any, index: int) -> Any:
    if not isinstance(item, dict):
        return item
    claim = _first_text(item, ISSUE_ALIASES["claim"])
    evidence = _first_text(item, ISSUE_ALIASES["evidence"])
    return {
        "id": str(item.get("id") or f"B{index + 1}"),
        "section": str(item.get("section") or "general"),
        "claim": claim,
        "evidence": evidence,
    }


def _normalize_suggestion(item: Any, index: int) -> Any:
    if not isinstance(item, dict):
        return item
    claim = _first_text(item, SUGGESTION_ALIASES["claim"])
    rationale = _first_text(item, SUGGESTION_ALIASES["rationale"])
    return {
        "id": str(item.get("id") or f"S{index + 1}"),
        "section": str(item.get("section") or "general"),
        "claim": claim,
        "rationale": rationale,
    }


def normalize_reviewer_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: payload[key] for key in TOP_LEVEL_FIELDS if key in payload}
    issues = normalized.get("blocking_issues")
    if isinstance(issues, list):
        normalized["blocking_issues"] = [
            _normalize_issue(item, index) for index, item in enumerate(issues)
        ]
    suggestions = normalized.get("suggestions")
    if isinstance(suggestions, list):
        normalized["suggestions"] = [
            _normalize_suggestion(item, index) for index, item in enumerate(suggestions)
        ]
    return normalized


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
        payload = normalize_reviewer_payload(payload)
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
            evidence=f"{exc}\n\nRaw: {raw_response[:300]}"[:500],
            raw_response=raw_response,
            elapsed_seconds=elapsed_seconds,
            retries=retries,
        )


def elapsed_since(start: float) -> float:
    return round(time.monotonic() - start, 3)
