from __future__ import annotations

import time

from krystal_quorum.models import ClauseStatus, ReviewIssue, ReviewerOutput, Verdict
from krystal_quorum.reviewers.base import elapsed_since


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
