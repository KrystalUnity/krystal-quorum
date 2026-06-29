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


def test_review_command_rejects_oversized_plan_before_reviewers_run(tmp_path, monkeypatch):
    plan = tmp_path / "huge-plan.md"
    plan.write_text("x" * 101, encoding="utf-8")
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("reviewers should not be built for oversized plans")

    monkeypatch.setattr("krystal_quorum.cli.build_reviewers", fail_if_called)

    result = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--reviewers",
            "mock",
            "--max-plan-chars",
            "100",
        ],
    )

    assert result.exit_code == 3
    assert called is False
    assert "Plan too large" in result.output
    assert "101 characters" in result.output
    assert "roughly 26 tokens" in result.output


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

    result = CliRunner().invoke(
        app, ["review", str(plan), "--reviewers", "mock", "--format", "json"]
    )

    assert result.exit_code == 0
    assert '"schema_version": "1.2"' in result.output
    assert '"diversity": "ok"' in result.output


def test_hosted_review_requires_api_token(tmp_path, monkeypatch):
    monkeypatch.delenv("KU_TOKEN", raising=False)
    plan = tmp_path / "plan.md"
    plan.write_text("## Plan\n- Verify", encoding="utf-8")

    result = CliRunner().invoke(app, ["review", str(plan), "--reviewers", "hosted:standard"])

    assert result.exit_code == 3
    assert "--api-token or KU_TOKEN is required for hosted reviewers" in result.output


def test_hosted_review_rejects_mixed_local_reviewers(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("## Plan\n- Verify", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--reviewers",
            "hosted:standard,mock",
            "--api-token",
            "kq_test",
        ],
    )

    assert result.exit_code == 3
    assert "hosted reviewers cannot be mixed with local reviewers" in result.output


def test_hosted_review_submits_polls_and_persists_artifacts(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    plan.write_text("## Plan\n- Verify", encoding="utf-8")
    out_dir = tmp_path / "reviews"
    calls: list[tuple[str, str, dict | None]] = []

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url, headers=None, json=None):
            calls.append(("POST", url, json))
            assert headers == {"Authorization": "Bearer kq_test"}
            return FakeResponse(
                {
                    "id": "run-1",
                    "status": "pending",
                    "poll_url": "/api/quorum/reviews/run-1",
                }
            )

        def get(self, url, headers=None):
            calls.append(("GET", url, None))
            assert headers == {"Authorization": "Bearer kq_test"}
            return FakeResponse(
                {
                    "id": "run-1",
                    "status": "completed",
                    "verdict": "REVISE",
                    "confidence": 0.82,
                    "credits_charged": 3,
                    "credits_remaining": 7,
                    "reviewers": ["command:claude", "command:codex", "command:agy"],
                    "reconciled": {
                        "schema_version": "krystal-quorum.v0.6",
                        "merged_verdict": "REVISE",
                        "confidence": 0.82,
                        "reviewers_used": ["command:claude", "command:codex", "command:agy"],
                    },
                    "artifacts": [
                        {
                            "name": "summary.md",
                            "content_type": "text/markdown",
                            "content": "# Summary\n",
                        },
                        {
                            "name": "round1/command_claude.json",
                            "content_type": "application/json",
                            "content": "{}",
                        },
                    ],
                }
            )

    monkeypatch.setattr("krystal_quorum.hosted.httpx.Client", FakeClient)

    result = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--reviewers",
            "hosted:standard",
            "--api-token",
            "kq_test",
            "--api-base-url",
            "https://ku.test",
            "--out-dir",
            str(out_dir),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["verdict"] == "REVISE"
    assert payload["credits_charged"] == 3
    assert payload["credits_remaining"] == 7
    run_dir = Path(payload["output_dir"])
    assert (run_dir / "plan_input.md").read_text(encoding="utf-8") == "## Plan\n- Verify"
    reconciled = json.loads((run_dir / "reconciled.json").read_text(encoding="utf-8"))
    assert reconciled["merged_verdict"] == "REVISE"
    assert (run_dir / "summary.md").read_text(encoding="utf-8") == "# Summary\n"
    assert (run_dir / "round1" / "command_claude.json").read_text(encoding="utf-8") == "{}"
    assert calls[0] == (
        "POST",
        "https://ku.test/api/quorum/reviews",
        {
            "plan_markdown": "## Plan\n- Verify",
            "pack_key": "standard",
            "source": "cli",
            "client_version": "krystal-quorum/0.6.5",
        },
    )
    assert calls[1] == ("GET", "https://ku.test/api/quorum/reviews/run-1", None)


def test_hosted_review_pretty_format_outputs_terminal_card(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    plan.write_text("## Plan\n- Verify", encoding="utf-8")

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url, headers=None, json=None):
            del url, headers, json
            return FakeResponse(
                {
                    "id": "run-1",
                    "status": "completed",
                    "verdict": "APPROVE",
                    "confidence": 0.91,
                    "credits_charged": 1,
                    "credits_remaining": 19,
                    "reviewers": ["hosted:quick"],
                    "reconciled": {
                        "abstained_reviewers": ["hosted:slow"],
                        "unresolved_for_human": ["One reviewer abstained."],
                    },
                }
            )

    monkeypatch.setattr("krystal_quorum.hosted.httpx.Client", FakeClient)

    result = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--reviewers",
            "hosted:quick",
            "--api-token",
            "kq_test",
            "--api-base-url",
            "https://ku.test",
            "--format",
            "pretty",
        ],
    )

    assert result.exit_code == 0
    assert "Krystal Quorum Hosted" in result.output
    assert "VERDICT: APPROVE" in result.output
    assert "Reviewers: hosted:quick" in result.output
    assert "Status: completed" in result.output
    assert "Credits: charged 1, remaining 19" in result.output
    assert "Abstained: hosted:slow" in result.output
    assert "Human Triage (1)" in result.output
    assert "One reviewer abstained." in result.output
    assert "Artifacts:" in result.output
    assert '"schema_version"' not in result.output


def test_hosted_review_failed_no_charge_persists_response_and_says_no_credits(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    plan.write_text("## Plan\n- Verify", encoding="utf-8")
    out_dir = tmp_path / "reviews"

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url, headers=None, json=None):
            del url, headers, json
            return FakeResponse(
                {
                    "id": "run-1",
                    "status": "failed_no_charge",
                    "error": "minimum usable quorum unavailable for quick: 0/2",
                    "verdict": "REVISE",
                    "credits_charged": 0,
                    "reconciled": {
                        "schema_version": "ku-quorum-hosted.v1",
                        "merged_verdict": "REVISE",
                        "abstained_reviewers": ["frontier-model-1", "specialised-coding-model-1"],
                        "unresolved_for_human": [
                            "All reviewers abstained; no usable review signal was produced."
                        ],
                    },
                }
            )

    monkeypatch.setattr("krystal_quorum.hosted.httpx.Client", FakeClient)

    result = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--reviewers",
            "hosted:quick",
            "--api-token",
            "kq_test",
            "--out-dir",
            str(out_dir),
        ],
    )

    assert result.exit_code == 3
    assert "minimum usable quorum unavailable for quick: 0/2" in result.output
    assert "No credits were charged." in result.output
    assert "Artifacts:" in result.output
    run_dirs = list(out_dir.glob("plan_*"))
    assert len(run_dirs) == 1
    persisted = json.loads((run_dirs[0] / "hosted-response.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "failed_no_charge"
    assert persisted["credits_charged"] == 0


def test_review_command_pretty_format_outputs_terminal_card(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("Build a CLI with no success criteria.", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["review", str(plan), "--reviewers", "mock", "--format", "pretty"],
    )

    assert result.exit_code == 1
    assert "Krystal Quorum" in result.output
    assert "VERDICT: REVISE" in result.output
    assert "Singleton Blockers" in result.output
    assert "Human Triage" in result.output
    assert "Artifacts:" in result.output
    assert '"schema_version"' not in result.output


def test_demo_command_runs_bundled_bad_plan_from_empty_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["demo"])

    assert result.exit_code == 0
    assert "VERDICT: REVISE" in result.output
    assert "examples" not in result.output
    assert list((tmp_path / ".krystal-quorum" / "reviews").glob("bad-plan_*"))


def test_demo_command_can_run_bundled_good_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["demo", "--plan", "good"])

    assert result.exit_code == 0
    assert "VERDICT: APPROVE" in result.output
    assert list((tmp_path / ".krystal-quorum" / "reviews").glob("good-plan_*"))


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


def test_review_command_outputs_abstentions_and_human_triage(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    plan.write_text("## Acceptance\n- Works", encoding="utf-8")

    class AbstainingReviewer:
        def __init__(self, reviewer_id: str, verdict: Verdict) -> None:
            self.id = reviewer_id
            self.verdict = verdict

        async def review_round1(self, plan_text: str, *, timeout_s: int) -> ReviewerOutput:
            del plan_text, timeout_s
            return ReviewerOutput(
                reviewer=self.id,
                round=1,
                verdict=self.verdict,
                confidence=0.8 if self.verdict != Verdict.ABSTAIN else 0.0,
                blocking_issues=[],
                suggestions=[],
                per_clause={},
                raw_response="{}",
                elapsed_seconds=0.1,
            )

        async def review_round2(
            self, plan_text: str, round1_outputs: list[ReviewerOutput], *, timeout_s: int
        ) -> ReviewerOutput:
            del round1_outputs
            return await self.review_round1(plan_text, timeout_s=timeout_s)

    monkeypatch.setattr(
        "krystal_quorum.cli.build_reviewers",
        lambda reviewers, config_path=None: [
            AbstainingReviewer("a", Verdict.APPROVE),
            AbstainingReviewer("b", Verdict.ABSTAIN),
            AbstainingReviewer("c", Verdict.ABSTAIN),
        ],
    )

    result = CliRunner().invoke(app, ["review", str(plan), "--reviewers", "a,b,c"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["verdict"] == "REVISE"
    assert payload["abstained_reviewers"] == ["b", "c"]
    assert payload["unresolved_for_human"] == [
        "Quorum collapsed: only 1 of 3 reviewers produced usable output."
    ]
