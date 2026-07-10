from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from krystal_quorum.diff_models import (
    DIFF_CLAUSE_IDS,
    CoverageStatus,
    DiffCoverageItem,
    DiffEvidenceFile,
    DiffReviewerOutput,
)
from krystal_quorum.models import ClauseStatus, ReviewIssue, ReviewerOutput, Verdict
from krystal_quorum.reviewers.base import elapsed_since
from krystal_quorum.reviewers.diff_base import expected_commitment_ids


class MockReviewer:
    id = "mock"

    async def review_round1(self, plan_text: str, *, timeout_s: int) -> ReviewerOutput:
        del timeout_s
        start = time.monotonic()
        has_acceptance = "acceptance" in plan_text.lower()
        issues: list[ReviewIssue] = []
        if not has_acceptance:
            issues.append(
                ReviewIssue(
                    id="B1",
                    section="Acceptance",
                    claim="The plan does not include explicit acceptance criteria.",
                    evidence="No heading or paragraph containing 'acceptance' was found.",
                )
            )
        return ReviewerOutput(
            reviewer=self.id,
            round=1,
            verdict=Verdict.APPROVE if not issues else Verdict.REVISE,
            confidence=0.9,
            blocking_issues=issues,
            suggestions=[],
            per_clause={
                "acceptance.1": ClauseStatus.SATISFIED
                if has_acceptance
                else ClauseStatus.UNSATISFIED
            },
            raw_response="mock deterministic review",
            elapsed_seconds=elapsed_since(start),
        )

    async def review_round2(
        self, plan_text: str, round1_outputs: list[ReviewerOutput], *, timeout_s: int
    ) -> ReviewerOutput:
        del round1_outputs
        return await self.review_round1(plan_text, timeout_s=timeout_s)

    async def review_diff_round1(
        self,
        review_input: str,
        commitments: Sequence[Any],
        changed_files: Sequence[DiffEvidenceFile],
        *,
        timeout_s: int,
    ) -> DiffReviewerOutput:
        return self._review_diff(
            review_input,
            commitments,
            changed_files,
            round_number=1,
            timeout_s=timeout_s,
        )

    async def review_diff_round2(
        self,
        review_input: str,
        commitments: Sequence[Any],
        changed_files: Sequence[DiffEvidenceFile],
        round1_outputs: list[DiffReviewerOutput],
        *,
        timeout_s: int,
    ) -> DiffReviewerOutput:
        del round1_outputs
        return self._review_diff(
            review_input,
            commitments,
            changed_files,
            round_number=2,
            timeout_s=timeout_s,
        )

    def _review_diff(
        self,
        review_input: str,
        commitments: Sequence[Any],
        changed_files: Sequence[DiffEvidenceFile],
        *,
        round_number: int,
        timeout_s: int,
    ) -> DiffReviewerOutput:
        del review_input, changed_files, timeout_s
        start = time.monotonic()
        if not commitments:
            return DiffReviewerOutput(
                reviewer=self.id,
                round=round_number,  # type: ignore[arg-type]
                verdict=Verdict.ABSTAIN,
                confidence=0.0,
                commitment_coverage=[],
                scope_findings=[],
                blocking_issues=[
                    ReviewIssue(
                        id="B0",
                        section="runtime",
                        claim="reviewer abstained: no expected commitments were supplied",
                        evidence="diff structural smoke test requires at least one commitment",
                    )
                ],
                suggestions=[],
                per_clause={clause_id: ClauseStatus.UNCLEAR for clause_id in DIFF_CLAUSE_IDS},
                raw_response="mock deterministic structural smoke test",
                elapsed_seconds=elapsed_since(start),
            )
        commitment_ids = expected_commitment_ids(commitments)
        coverage = [
            DiffCoverageItem(
                commitment_id=commitment_id,
                status=CoverageStatus.NOT_EVIDENT,
                claim="Structural smoke test does not infer implementation coverage.",
                evidence=None,
                path=None,
                line_start=None,
            )
            for commitment_id in commitment_ids
        ]
        return DiffReviewerOutput(
            reviewer=self.id,
            round=round_number,  # type: ignore[arg-type]
            verdict=Verdict.REVISE,
            confidence=1.0,
            commitment_coverage=coverage,
            scope_findings=[],
            blocking_issues=[],
            suggestions=[],
            per_clause={
                clause_id: ClauseStatus.UNCLEAR
                for clause_id in DIFF_CLAUSE_IDS
            },
            raw_response="mock deterministic structural smoke test",
            elapsed_seconds=elapsed_since(start),
        )
