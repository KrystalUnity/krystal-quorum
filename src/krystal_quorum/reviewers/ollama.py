from __future__ import annotations

import time
from typing import Any

import httpx

from krystal_quorum.models import ReviewerOutput
from krystal_quorum.prompts import round1_prompt, round2_prompt
from krystal_quorum.reviewers.base import elapsed_since, fallback_output, parse_reviewer_output


class OllamaReviewer:
    def __init__(
        self,
        *,
        reviewer_id: str,
        model: str,
        base_url: str = "http://localhost:11434",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.id = reviewer_id
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def review_round1(self, plan_text: str, *, timeout_s: int) -> ReviewerOutput:
        return await self._review(round1_prompt(self.id, plan_text), 1, timeout_s)

    async def review_round2(
        self, plan_text: str, round1_outputs: list[ReviewerOutput], *, timeout_s: int
    ) -> ReviewerOutput:
        return await self._review(round2_prompt(self.id, plan_text, round1_outputs), 2, timeout_s)

    async def _review(self, prompt: str, round_number: int, timeout_s: int) -> ReviewerOutput:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=timeout_s) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                response.raise_for_status()
                raw = self._extract_text(response.json())
        except Exception as exc:
            return fallback_output(
                self.id,
                round_number,
                claim=f"reviewer request failed: {type(exc).__name__}",
                evidence=str(exc),
                elapsed_seconds=elapsed_since(start),
            )
        return parse_reviewer_output(
            self.id,
            round_number,
            raw,
            elapsed_seconds=elapsed_since(start),
            retries=0,
        )

    def _extract_text(self, payload: dict[str, Any]) -> str:
        message = payload.get("message")
        if isinstance(message, dict):
            content = message.get("content") or message.get("reasoning") or ""
            return content if isinstance(content, str) else str(content)
        return ""
