from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Verdict(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    BLOCK = "BLOCK"
    ABSTAIN = "ABSTAIN"


class ClauseStatus(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    NA = "N/A"
    UNCLEAR = "UNCLEAR"


class ReviewIssue(StrictModel):
    id: str
    section: str
    claim: str
    evidence: str


class ReviewSuggestion(StrictModel):
    id: str
    section: str
    claim: str
    rationale: str


class ReviewerOutput(StrictModel):
    reviewer: str
    round: Literal[1, 2]
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    blocking_issues: list[ReviewIssue]
    suggestions: list[ReviewSuggestion]
    per_clause: dict[str, ClauseStatus]
    raw_response: str
    elapsed_seconds: float
    retries: int = 0


class ContradictionFinding(StrictModel):
    clause_id: str
    reviewer_positions: dict[str, ClauseStatus]
    severity: Literal["high", "medium", "low"]


class ReviewerFamily(StrictModel):
    reviewer: str
    backend: str
    family: str


class DiversityReport(StrictModel):
    status: Literal["ok", "low"]
    reviewers: list[ReviewerFamily]
    reason: str | None = None


class Round2Comparison(StrictModel):
    reviewer: str
    round1: Verdict | None
    round2: Verdict | None
    comparable: bool
    changed: bool | None


class ReconciledVerdict(StrictModel):
    schema_version: str
    plan_path: str
    plan_sha256: str
    timestamp: str
    reviewers_used: list[str]
    diversity: DiversityReport
    abstained_reviewers: list[str]
    merged_verdict: Verdict
    confidence: float
    shared_blocking_issues: list[ReviewIssue]
    singleton_blocking_issues: list[ReviewIssue]
    contradictions: list[ContradictionFinding]
    unresolved_for_human: list[str]
    round1_outputs: list[ReviewerOutput]
    round2_outputs: list[ReviewerOutput]
    round2_delta: int | None
    round2_comparisons: list[Round2Comparison]
