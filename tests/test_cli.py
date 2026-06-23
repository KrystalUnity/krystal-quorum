import asyncio
import json
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


def test_review_command_can_require_reviewer_diversity(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("## Acceptance\n- Works", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--reviewers",
            "ollama:qwen2.5:14b,ollama:qwen2.5:32b",
            "--require-diversity",
        ],
    )

    assert result.exit_code == 3
    assert "reviewer diversity is low" in result.output


def test_review_command_can_require_command_reviewer_family_override(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("## Acceptance\n- Works", encoding="utf-8")
    config = tmp_path / "krystal-quorum.toml"
    config.write_text(
        """
        [reviewers.local-a]
        type = "command"
        command = ["python", "-c", "print('{}')"]
        family = "same-local"

        [reviewers.local-b]
        type = "command"
        command = ["python", "-c", "print('{}')"]
        family = "same-local"
        """,
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--config",
            str(config),
            "--reviewers",
            "command:local-a,command:local-b",
            "--require-diversity",
        ],
    )

    assert result.exit_code == 3
    assert "same-local" in result.output


def test_review_command_outputs_diversity_and_schema_version(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("## Acceptance\n- Works", encoding="utf-8")

    result = CliRunner().invoke(app, ["review", str(plan), "--reviewers", "mock"])

    assert result.exit_code == 0
    assert '"schema_version": "1.2"' in result.output
    assert '"diversity": "ok"' in result.output


def test_review_command_outputs_diversity_reason_and_round2_comparisons(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("## Acceptance\n- Works", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--reviewers",
            "mock,mock",
            "--round2",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["diversity"] == "low"
    assert "mock" in payload["diversity_reason"]
    assert payload["diversity_reviewers"] == [
        {"reviewer": "mock", "backend": "mock", "family": "mock"},
        {"reviewer": "mock", "backend": "mock", "family": "mock"},
    ]
    assert payload["round2_delta"] == 0
    assert payload["round2_comparisons"] == [
        {
            "reviewer": "mock",
            "round1": "APPROVE",
            "round2": "APPROVE",
            "comparable": True,
            "changed": False,
        },
        {
            "reviewer": "mock",
            "round1": "APPROVE",
            "round2": "APPROVE",
            "comparable": True,
            "changed": False,
        },
    ]
