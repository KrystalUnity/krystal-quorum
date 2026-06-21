import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from krystal_quorum.cli import _run_review, app
from krystal_quorum.models import ReviewerOutput, Verdict


def test_cli_help_runs():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "review" in result.output


def test_review_command_writes_output(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("Build a CLI with no success criteria.", encoding="utf-8")
    out_dir = tmp_path / "reviews"

    result = CliRunner().invoke(
        app,
        ["review", str(plan), "--reviewers", "mock", "--out-dir", str(out_dir)],
    )

    assert result.exit_code == 1
    assert list(out_dir.glob("plan_*"))


class CoordinatedReviewer:
    def __init__(
        self,
        reviewer_id: str,
        started: list[str],
        all_started: asyncio.Event,
    ) -> None:
        self.id = reviewer_id
        self.started = started
        self.all_started = all_started

    async def review_round1(self, plan_text: str, *, timeout_s: int) -> ReviewerOutput:
        del plan_text, timeout_s
        return self._output(round_number=1)

    async def review_round2(
        self, plan_text: str, round1_outputs: list[ReviewerOutput], *, timeout_s: int
    ) -> ReviewerOutput:
        del plan_text, round1_outputs, timeout_s
        self.started.append(self.id)
        if len(self.started) == 2:
            self.all_started.set()
        await asyncio.wait_for(self.all_started.wait(), timeout=0.2)
        return self._output(round_number=2)

    def _output(self, *, round_number: int) -> ReviewerOutput:
        return ReviewerOutput(
            reviewer=self.id,
            round=round_number,  # type: ignore[arg-type]
            verdict=Verdict.APPROVE,
            confidence=0.8,
            blocking_issues=[],
            suggestions=[],
            per_clause={},
            raw_response="{}",
            elapsed_seconds=0.1,
        )


@pytest.mark.asyncio
async def test_run_review_runs_round2_reviewers_concurrently(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("## Acceptance\n- Works", encoding="utf-8")
    started: list[str] = []
    all_started = asyncio.Event()
    reviewers = [
        CoordinatedReviewer("a", started, all_started),
        CoordinatedReviewer("b", started, all_started),
    ]

    result = await _run_review(plan, reviewers, run_round2=True)

    assert [output.reviewer for output in result.round2_outputs] == ["a", "b"]


def test_review_command_reads_plan_once(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    plan.write_text("## Acceptance\n- Works", encoding="utf-8")
    out_dir = tmp_path / "reviews"
    read_count = 0
    original_read_text = Path.read_text

    def counting_read_text(self: Path, *args, **kwargs):
        nonlocal read_count
        if self == plan:
            read_count += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    monkeypatch.setattr("krystal_quorum.cli.persist_run", lambda *args: out_dir / "run")

    result = CliRunner().invoke(
        app,
        ["review", str(plan), "--reviewers", "mock", "--out-dir", str(out_dir)],
    )

    assert result.exit_code == 0
    assert read_count == 1
