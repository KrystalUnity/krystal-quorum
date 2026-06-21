from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from collections.abc import Mapping, Sequence

from krystal_quorum.models import ReviewerOutput
from krystal_quorum.prompts import round1_prompt, round2_prompt
from krystal_quorum.reviewers.base import elapsed_since, fallback_output, parse_reviewer_output


class CommandReviewer:
    def __init__(
        self,
        *,
        reviewer_id: str,
        command: Sequence[str],
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        output_file: Path | None = None,
        timeout_s: float | None = None,
        wait_for_output_s: float = 0.0,
        family: str | None = None,
    ) -> None:
        if not command:
            raise ValueError("command reviewer command must not be empty")
        self.id = reviewer_id
        self.command = [str(part) for part in command]
        self.cwd = cwd
        self.env = dict(env or {})
        self.output_file = output_file
        self.timeout_s = timeout_s
        self.wait_for_output_s = wait_for_output_s
        self.family = family

    async def review_round1(self, plan_text: str, *, timeout_s: int) -> ReviewerOutput:
        return await self._review(round1_prompt(self.id, plan_text), 1, timeout_s)

    async def review_round2(
        self, plan_text: str, round1_outputs: list[ReviewerOutput], *, timeout_s: int
    ) -> ReviewerOutput:
        return await self._review(round2_prompt(self.id, plan_text, round1_outputs), 2, timeout_s)

    async def _review(
        self,
        prompt: str,
        round_number: int,
        requested_timeout_s: float,
    ) -> ReviewerOutput:
        start = time.monotonic()
        command_timeout_s = self.timeout_s if self.timeout_s is not None else requested_timeout_s
        try:
            if self.output_file is not None:
                self.output_file.parent.mkdir(parents=True, exist_ok=True)
                self.output_file.unlink(missing_ok=True)
            process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.cwd) if self.cwd is not None else None,
                env=self._subprocess_env(),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=command_timeout_s,
                )
            except TimeoutError:
                process.kill()
                stdout_bytes, stderr_bytes = await process.communicate()
                raw = self._decode(stdout_bytes, stderr_bytes)
                return fallback_output(
                    self.id,
                    round_number,
                    claim="reviewer command timeout",
                    evidence=f"timeout after {command_timeout_s:g}s",
                    raw_response=raw,
                    elapsed_seconds=elapsed_since(start),
                )
        except Exception as exc:
            return fallback_output(
                self.id,
                round_number,
                claim=f"reviewer command failed: {type(exc).__name__}",
                evidence=str(exc),
                elapsed_seconds=elapsed_since(start),
            )

        output_file_text = await self._read_output_file()
        raw = output_file_text or self._decode(stdout_bytes, stderr_bytes)
        if not raw.strip():
            return fallback_output(
                self.id,
                round_number,
                claim="reviewer command produced empty output",
                evidence=f"exit code: {process.returncode}",
                raw_response=raw,
                elapsed_seconds=elapsed_since(start),
            )
        return parse_reviewer_output(
            self.id,
            round_number,
            raw,
            elapsed_seconds=elapsed_since(start),
            retries=0,
        )

    async def _read_output_file(self) -> str:
        if self.output_file is None:
            return ""
        deadline = time.monotonic() + self.wait_for_output_s
        while True:
            if self.output_file.exists():
                text = self.output_file.read_text(encoding="utf-8")
                if text.strip():
                    return text
            if self.wait_for_output_s <= 0 or time.monotonic() >= deadline:
                return ""
            await asyncio.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    def _subprocess_env(self) -> dict[str, str] | None:
        if not self.env:
            return None
        merged = os.environ.copy()
        merged.update(self.env)
        return merged

    def _decode(self, stdout_bytes: bytes, stderr_bytes: bytes) -> str:
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return "\n".join(part for part in (stdout, stderr) if part).strip()
