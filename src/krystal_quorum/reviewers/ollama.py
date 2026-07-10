from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Sequence
from typing import Any

import httpx

from krystal_quorum.diff_models import DiffEvidenceFile, DiffReviewerOutput
from krystal_quorum.diff_prompts import diff_round1_prompt, diff_round2_prompt
from krystal_quorum.models import ReviewerOutput
from krystal_quorum.prompts import round1_prompt, round2_prompt
from krystal_quorum.reviewers.base import (
    PARSE_RETRIES,
    TRANSPORT_RETRIES,
    TRANSPORT_RETRY_BACKOFF_S,
    combined_raw_attempts,
    elapsed_since,
    fallback_output,
    is_parse_failure,
    parse_reviewer_output,
    retry_prompt,
)
from krystal_quorum.reviewers.diff_base import (
    diff_fallback_output,
    is_diff_parse_failure,
    parse_diff_reviewer_output,
)

ReviewOutput = ReviewerOutput | DiffReviewerOutput


class OllamaReviewer:
    def __init__(
        self,
        *,
        reviewer_id: str,
        model: str,
        base_url: str = "http://localhost:11434",
        transport: httpx.AsyncBaseTransport | None = None,
        think: bool | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.id = reviewer_id
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.think = think
        self.options = options or {}

    async def review_round1(self, plan_text: str, *, timeout_s: int) -> ReviewerOutput:
        return await self._review(round1_prompt(self.id, plan_text), 1, timeout_s)

    async def review_round2(
        self, plan_text: str, round1_outputs: list[ReviewerOutput], *, timeout_s: int
    ) -> ReviewerOutput:
        return await self._review(round2_prompt(self.id, plan_text, round1_outputs), 2, timeout_s)

    async def review_diff_round1(
        self,
        review_input: str,
        commitments: Sequence[Any],
        changed_files: Sequence[DiffEvidenceFile],
        *,
        timeout_s: int,
    ) -> DiffReviewerOutput:
        output = await self._review(
            diff_round1_prompt(self.id, review_input, commitments),
            1,
            timeout_s,
            commitments=commitments,
            changed_files=changed_files,
        )
        assert isinstance(output, DiffReviewerOutput)
        return output

    async def review_diff_round2(
        self,
        review_input: str,
        commitments: Sequence[Any],
        changed_files: Sequence[DiffEvidenceFile],
        round1_outputs: list[DiffReviewerOutput],
        *,
        timeout_s: int,
    ) -> DiffReviewerOutput:
        output = await self._review(
            diff_round2_prompt(self.id, review_input, commitments, round1_outputs),
            2,
            timeout_s,
            commitments=commitments,
            changed_files=changed_files,
        )
        assert isinstance(output, DiffReviewerOutput)
        return output

    async def _review(
        self,
        prompt: str,
        round_number: int,
        timeout_s: int,
        *,
        commitments: Sequence[Any] | None = None,
        changed_files: Sequence[DiffEvidenceFile] | None = None,
    ) -> ReviewOutput:
        start = time.monotonic()
        raw_attempts: list[str] = []
        transport_retries = 0
        for parse_retries in range(PARSE_RETRIES + 1):
            attempt_prompt = prompt if parse_retries == 0 else retry_prompt(prompt)
            raw: str | None = None
            for request_retries in range(TRANSPORT_RETRIES + 1):
                try:
                    async with httpx.AsyncClient(
                        transport=self.transport, timeout=timeout_s
                    ) as client:
                        payload: dict[str, Any] = {
                            "model": self.model,
                            "stream": False,
                            "messages": [{"role": "user", "content": attempt_prompt}],
                        }
                        if self.think is not None:
                            payload["think"] = self.think
                        if self.options:
                            payload["options"] = self.options
                        response = await client.post(f"{self.base_url}/api/chat", json=payload)
                        response.raise_for_status()
                        raw = self._extract_text(response.json())
                    break
                except httpx.HTTPError as exc:
                    if request_retries >= TRANSPORT_RETRIES:
                        return self._fallback(
                            round_number,
                            commitments,
                            f"reviewer request failed: {type(exc).__name__}",
                            str(exc),
                            elapsed_since(start),
                            transport_retries + parse_retries,
                        )
                    transport_retries += 1
                    await asyncio.sleep(TRANSPORT_RETRY_BACKOFF_S * (2**request_retries))
                except Exception as exc:
                    return self._fallback(
                        round_number,
                        commitments,
                        f"reviewer request failed: {type(exc).__name__}",
                        str(exc),
                        elapsed_since(start),
                        transport_retries + parse_retries,
                    )
            if raw is None:
                continue
            raw_attempts.append(raw)
            total_retries = transport_retries + parse_retries
            if commitments is None:
                output = parse_reviewer_output(
                    self.id,
                    round_number,
                    raw,
                    elapsed_seconds=elapsed_since(start),
                    retries=total_retries,
                )
                parse_failed = is_parse_failure(output)
            else:
                output = parse_diff_reviewer_output(
                    self.id,
                    round_number,
                    raw,
                    elapsed_seconds=elapsed_since(start),
                    retries=total_retries,
                    commitments=commitments,
                    changed_files=changed_files or (),
                )
                parse_failed = is_diff_parse_failure(output)
            if len(raw_attempts) > 1:
                output.raw_response = combined_raw_attempts(raw_attempts)
            if not parse_failed or parse_retries >= PARSE_RETRIES:
                return output
        return self._fallback(
            round_number,
            commitments,
            "reviewer retry loop exhausted",
            "",
            elapsed_since(start),
            transport_retries + PARSE_RETRIES,
        )

    def _fallback(
        self,
        round_number: int,
        commitments: Sequence[Any] | None,
        claim: str,
        evidence: str,
        elapsed_seconds: float,
        retries: int,
    ) -> ReviewOutput:
        if commitments is None:
            return fallback_output(
                self.id,
                round_number,
                claim=claim,
                evidence=evidence,
                elapsed_seconds=elapsed_seconds,
                retries=retries,
            )
        return diff_fallback_output(
            self.id,
            round_number,
            commitments,
            claim=claim,
            evidence=evidence,
            elapsed_seconds=elapsed_seconds,
            retries=retries,
        )

    def _extract_text(self, payload: dict[str, Any]) -> str:
        message = payload.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
            reasoning = message.get("reasoning")
            if isinstance(reasoning, str) and re.search(
                r"<json>.*?</json>", reasoning, flags=re.DOTALL | re.IGNORECASE
            ):
                return reasoning
        return ""
