import json
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from krystal_quorum.cli import app
from krystal_quorum.config import build_reviewers
from krystal_quorum.models import Verdict


def _write_script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "reviewer.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


def _write_config(
    tmp_path: Path,
    *,
    name: str,
    command: list[str],
    output_file: Path | None = None,
    timeout_s: float | None = None,
    wait_for_output_s: float | None = None,
) -> Path:
    config = tmp_path / "krystal-quorum.toml"
    lines = [
        f"[reviewers.{name}]",
        'type = "command"',
        f"command = {json.dumps(command)}",
    ]
    if output_file is not None:
        lines.append(f"output_file = {json.dumps(str(output_file))}")
    if timeout_s is not None:
        lines.append(f"timeout_s = {timeout_s}")
    if wait_for_output_s is not None:
        lines.append(f"wait_for_output_s = {wait_for_output_s}")
    config.write_text("\n".join(lines), encoding="utf-8")
    return config


@pytest.mark.asyncio
async def test_command_reviewer_reads_stdout_json(tmp_path):
    script = _write_script(
        tmp_path,
        """
        import json
        import sys

        prompt = sys.stdin.read()
        if "PLAN:" not in prompt:
            raise SystemExit(2)
        print(json.dumps({
            "verdict": "APPROVE",
            "confidence": 0.91,
            "blocking_issues": [],
            "suggestions": [],
            "per_clause": {}
        }))
        """,
    )
    config = _write_config(
        tmp_path,
        name="echo",
        command=[sys.executable, str(script)],
    )
    reviewer = build_reviewers("command:echo", config_path=config)[0]

    output = await reviewer.review_round1("## Acceptance\n- Works", timeout_s=5)

    assert reviewer.id == "command:echo"
    assert output.verdict == Verdict.APPROVE


@pytest.mark.asyncio
async def test_command_reviewer_extracts_json_from_noisy_stdout(tmp_path):
    script = _write_script(
        tmp_path,
        """
        import json
        import sys

        sys.stdin.read()
        print("mcp auth warning before useful output")
        print(json.dumps({
            "verdict": "BLOCK",
            "confidence": 0.8,
            "blocking_issues": [{
                "id": "B1",
                "section": "Tests",
                "claim": "The plan omits a verification step.",
                "evidence": "No test command is listed."
            }],
            "suggestions": [],
            "per_clause": {}
        }))
        print("resume with local-review --continue xyz")
        """,
    )
    config = _write_config(
        tmp_path,
        name="noisy",
        command=[sys.executable, str(script)],
    )
    reviewer = build_reviewers("command:noisy", config_path=config)[0]

    output = await reviewer.review_round1("plan", timeout_s=5)

    assert output.verdict == Verdict.BLOCK
    assert output.blocking_issues[0].id == "B1"


@pytest.mark.asyncio
async def test_command_reviewer_reads_json_from_output_file(tmp_path):
    output_file = tmp_path / "review.json"
    script = _write_script(
        tmp_path,
        """
        import json
        import sys
        from pathlib import Path

        sys.stdin.read()
        Path(sys.argv[1]).write_text(json.dumps({
            "verdict": "REVISE",
            "confidence": 0.65,
            "blocking_issues": [],
            "suggestions": [{
                "id": "S1",
                "section": "Rollback",
                "claim": "Add an explicit rollback note.",
                "rationale": "Local agent reviews should preserve recovery steps."
            }],
            "per_clause": {}
        }), encoding="utf-8")
        print("review saved")
        """,
    )
    config = _write_config(
        tmp_path,
        name="fileout",
        command=[sys.executable, str(script), str(output_file)],
        output_file=output_file,
    )
    reviewer = build_reviewers("command:fileout", config_path=config)[0]

    output = await reviewer.review_round1("plan", timeout_s=5)

    assert output.verdict == Verdict.REVISE
    assert output.suggestions[0].id == "S1"


@pytest.mark.asyncio
async def test_command_reviewer_waits_for_delayed_output_file(tmp_path):
    output_file = tmp_path / "review.json"
    script = _write_script(
        tmp_path,
        """
        import subprocess
        import sys

        sys.stdin.read()
        subprocess.Popen([
            sys.executable,
            "-c",
            (
                "import json, sys, time; "
                "time.sleep(0.2); "
                "open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps({"
                "'verdict': 'APPROVE', "
                "'confidence': 0.88, "
                "'blocking_issues': [], "
                "'suggestions': [], "
                "'per_clause': {}"
                "}))"
            ),
            sys.argv[1],
        ])
        print("review launched")
        """,
    )
    config = _write_config(
        tmp_path,
        name="delayed",
        command=[sys.executable, str(script), str(output_file)],
        output_file=output_file,
        wait_for_output_s=2,
    )
    reviewer = build_reviewers("command:delayed", config_path=config)[0]

    output = await reviewer.review_round1("plan", timeout_s=5)

    assert output.verdict == Verdict.APPROVE


@pytest.mark.asyncio
async def test_command_reviewer_empty_output_abstains(tmp_path):
    script = _write_script(
        tmp_path,
        """
        import sys

        sys.stdin.read()
        """,
    )
    config = _write_config(
        tmp_path,
        name="empty",
        command=[sys.executable, str(script)],
    )
    reviewer = build_reviewers("command:empty", config_path=config)[0]

    output = await reviewer.review_round1("plan", timeout_s=5)

    assert output.verdict == Verdict.ABSTAIN
    assert output.reviewer == "command:empty"


@pytest.mark.asyncio
async def test_command_reviewer_timeout_abstains(tmp_path):
    script = _write_script(
        tmp_path,
        """
        import time

        time.sleep(5)
        """,
    )
    config = _write_config(
        tmp_path,
        name="slow",
        command=[sys.executable, str(script)],
    )
    reviewer = build_reviewers("command:slow", config_path=config)[0]

    output = await reviewer.review_round1("plan", timeout_s=0.1)

    assert output.verdict == Verdict.ABSTAIN
    assert "timeout" in output.blocking_issues[0].claim


def test_build_reviewers_loads_command_from_config(tmp_path):
    script = _write_script(
        tmp_path,
        """
        import json

        print(json.dumps({
            "verdict": "APPROVE",
            "confidence": 0.9,
            "blocking_issues": [],
            "suggestions": [],
            "per_clause": {}
        }))
        """,
    )
    config = _write_config(
        tmp_path,
        name="echo",
        command=[sys.executable, str(script)],
    )

    reviewers = build_reviewers("mock,command:echo", config_path=config)

    assert [reviewer.id for reviewer in reviewers] == ["mock", "command:echo"]


def test_build_reviewers_reports_missing_config_file(tmp_path):
    with pytest.raises(ValueError, match="could not read config"):
        build_reviewers("command:echo", config_path=tmp_path / "missing.toml")


def test_cli_uses_command_reviewer_config(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("## Acceptance\n- Works", encoding="utf-8")
    out_dir = tmp_path / "reviews"
    script = _write_script(
        tmp_path,
        """
        import json
        import sys

        sys.stdin.read()
        print(json.dumps({
            "verdict": "APPROVE",
            "confidence": 0.9,
            "blocking_issues": [],
            "suggestions": [],
            "per_clause": {}
        }))
        """,
    )
    config = _write_config(
        tmp_path,
        name="echo",
        command=[sys.executable, str(script)],
    )

    result = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--config",
            str(config),
            "--reviewers",
            "command:echo",
            "--out-dir",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0
    assert "command:echo" in result.output
    assert list(out_dir.glob("plan_*"))
