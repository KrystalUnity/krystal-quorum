from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from krystal_quorum.diff_models import DiffEvidenceFile, DiffReviewerOutput
from krystal_quorum.diff_prompts import diff_round1_prompt, diff_round2_prompt
from krystal_quorum.models import ReviewerOutput
from krystal_quorum.prompts import round1_prompt, round2_prompt
from krystal_quorum.reviewers.base import (
    PARSE_RETRIES,
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
FallbackFactory = Callable[..., ReviewOutput]


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
        requested_timeout_s: float,
        *,
        commitments: Sequence[Any] | None = None,
        changed_files: Sequence[DiffEvidenceFile] | None = None,
    ) -> ReviewOutput:
        start = time.monotonic()
        command_timeout_s = self.timeout_s if self.timeout_s is not None else requested_timeout_s
        raw_attempts: list[str] = []
        fallback_factory: FallbackFactory = (
            fallback_output if commitments is None else diff_fallback_output
        )
        for retries in range(PARSE_RETRIES + 1):
            attempt_prompt = prompt if retries == 0 else retry_prompt(prompt)
            raw = await self._run_command_once(
                attempt_prompt,
                round_number,
                command_timeout_s,
                start,
                retries,
                fallback_factory,
                commitments,
            )
            if isinstance(raw, (ReviewerOutput, DiffReviewerOutput)):
                return raw
            if not raw.strip():
                fallback_args: list[Any] = [self.id, round_number]
                if commitments is not None:
                    fallback_args.append(commitments)
                return fallback_factory(
                    *fallback_args,
                    claim="reviewer command produced empty output",
                    evidence="command produced no stdout/stderr or output file text",
                    raw_response=raw,
                    elapsed_seconds=elapsed_since(start),
                    retries=retries,
                )
            raw_attempts.append(raw)
            if commitments is None:
                output = parse_reviewer_output(
                    self.id,
                    round_number,
                    raw,
                    elapsed_seconds=elapsed_since(start),
                    retries=retries,
                )
                parse_failed = is_parse_failure(output)
            else:
                output = parse_diff_reviewer_output(
                    self.id,
                    round_number,
                    raw,
                    elapsed_seconds=elapsed_since(start),
                    retries=retries,
                    commitments=commitments,
                    changed_files=changed_files or (),
                )
                parse_failed = is_diff_parse_failure(output)
            if len(raw_attempts) > 1:
                output.raw_response = combined_raw_attempts(raw_attempts)
            if not parse_failed or retries >= PARSE_RETRIES:
                return output
        fallback_args = [self.id, round_number]
        if commitments is not None:
            fallback_args.append(commitments)
        return fallback_factory(
            *fallback_args,
            claim="reviewer retry loop exhausted",
            elapsed_seconds=elapsed_since(start),
            retries=PARSE_RETRIES,
        )

    async def _run_command_once(
        self,
        prompt: str,
        round_number: int,
        command_timeout_s: float,
        start: float,
        retries: int,
        fallback_factory: FallbackFactory,
        commitments: Sequence[Any] | None,
    ) -> str | ReviewOutput:
        fallback_args: list[Any] = [self.id, round_number]
        if commitments is not None:
            fallback_args.append(commitments)
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
                return fallback_factory(
                    *fallback_args,
                    claim="reviewer command timeout",
                    evidence=f"timeout after {command_timeout_s:g}s",
                    raw_response=raw,
                    elapsed_seconds=elapsed_since(start),
                    retries=retries,
                )
        except Exception as exc:
            return fallback_factory(
                *fallback_args,
                claim=f"reviewer command failed: {type(exc).__name__}",
                evidence=str(exc),
                elapsed_seconds=elapsed_since(start),
                retries=retries,
            )

        output_file_text = await self._read_output_file()
        return output_file_text or self._decode(stdout_bytes, stderr_bytes)

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
