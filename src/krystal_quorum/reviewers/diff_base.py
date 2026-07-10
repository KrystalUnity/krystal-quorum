from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import re
from typing import Any

from pydantic import ValidationError

from krystal_quorum.diff_models import (
    DIFF_CLAUSE_IDS,
    DiffEvidenceFile,
    DiffReviewerOutput,
)
from krystal_quorum.models import ClauseStatus, ReviewIssue, Verdict
from krystal_quorum.reviewers.base import extract_json

COMMITMENT_ID = re.compile(r"^(AC|SCOPE|TEST|RB|SEC|DEP|OBS)-[1-9][0-9]*$")


def _commitment_id(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        value = item.get("id") or item.get("commitment_id")
    else:
        value = getattr(item, "id", None) or getattr(item, "commitment_id", None)
    if not isinstance(value, str) or not value:
        raise ValueError("commitments must supply non-empty IDs")
    return value


def expected_commitment_ids(commitments: Sequence[Any]) -> list[str]:
    ids = [_commitment_id(item) for item in commitments]
    if not ids:
        raise ValueError("expected commitment IDs must not be empty")
    if any(COMMITMENT_ID.fullmatch(commitment_id) is None for commitment_id in ids):
        raise ValueError("expected commitment IDs must use canonical uppercase IDs")
    if len(ids) != len(set(ids)):
        raise ValueError("expected commitment IDs must be unique")
    return ids


def _strict_evidence_files(changed_files: Sequence[Any]) -> list[DiffEvidenceFile]:
    files: list[DiffEvidenceFile] = []
    for item in changed_files:
        files.append(
            item if isinstance(item, DiffEvidenceFile) else DiffEvidenceFile.model_validate(item)
        )
    return files


def diff_fallback_output(
    reviewer: str,
    round_number: int,
    commitments: Sequence[Any],
    claim: str,
    evidence: str = "",
    raw_response: str = "",
    elapsed_seconds: float = 0.0,
    retries: int = 0,
) -> DiffReviewerOutput:
    expected_commitment_ids(commitments)
    return DiffReviewerOutput(
        reviewer=reviewer,
        round=round_number,  # type: ignore[arg-type]
        verdict=Verdict.ABSTAIN,
        confidence=0.0,
        commitment_coverage=[],
        scope_findings=[],
        blocking_issues=[
            ReviewIssue(
                id="B0",
                section="runtime",
                claim=f"reviewer abstained: {claim}",
                evidence=evidence[:500],
            )
        ],
        suggestions=[],
        per_clause={clause_id: ClauseStatus.UNCLEAR for clause_id in DIFF_CLAUSE_IDS},
        raw_response=raw_response,
        elapsed_seconds=elapsed_seconds,
        retries=retries,
    )


def _validate_exact_coverage(
    output: DiffReviewerOutput,
    commitments: Sequence[Any],
) -> None:
    expected = expected_commitment_ids(commitments)
    if output.verdict == Verdict.ABSTAIN:
        return
    actual = [item.commitment_id for item in output.commitment_coverage]
    if Counter(actual) != Counter(expected) or len(actual) != len(expected):
        raise ValueError("reviewer must assess every expected commitment ID exactly once")


def _validate_evidence_paths(
    output: DiffReviewerOutput,
    changed_files: Sequence[Any],
) -> None:
    files = _strict_evidence_files(changed_files)
    present = {item.path: item for item in files if item.status != "D"}
    metadata_only = {item.path for item in files if item.status == "D"}
    metadata_only.update(
        item.old_path for item in files if item.status == "R" and item.old_path is not None
    )

    for item in output.commitment_coverage:
        if item.status.value in {"IMPLEMENTED", "PARTIAL"} and item.path is None:
            raise ValueError(f"{item.status.value} coverage requires an authoritative path")
        _validate_location(item.path, item.line_start, present, metadata_only)
    for item in output.scope_findings:
        _validate_location(item.path, item.line_start, present, metadata_only)


def _validate_location(
    path: str | None,
    line_start: int | None,
    present: dict[str, DiffEvidenceFile],
    metadata_only: set[str],
) -> None:
    if path is None:
        return
    evidence_file = present.get(path)
    if evidence_file is not None:
        if evidence_file.kind == "text" and line_start is None:
            raise ValueError("present text evidence requires path and line_start")
        return
    if path in metadata_only:
        return
    raise ValueError("evidence path must identify an authoritative changed file")


def parse_diff_reviewer_output(
    reviewer: str,
    round_number: int,
    raw_response: str,
    elapsed_seconds: float,
    retries: int,
    commitments: Sequence[Any],
    changed_files: Sequence[Any],
) -> DiffReviewerOutput:
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
        output = DiffReviewerOutput.model_validate(payload)
        _validate_exact_coverage(output, commitments)
        _validate_evidence_paths(output, changed_files)
        return output
    except (ValidationError, TypeError, ValueError) as exc:
        return diff_fallback_output(
            reviewer,
            round_number,
            commitments,
            claim="reviewer output unparseable",
            evidence=f"{exc}\n\nRaw: {raw_response[:300]}"[:500],
            raw_response=raw_response,
            elapsed_seconds=elapsed_seconds,
            retries=retries,
        )


def is_diff_parse_failure(output: DiffReviewerOutput) -> bool:
    return (
        output.verdict == Verdict.ABSTAIN
        and bool(output.blocking_issues)
        and output.blocking_issues[0].id == "B0"
        and "output unparseable" in output.blocking_issues[0].claim
    )
