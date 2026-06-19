from typer.testing import CliRunner

from krystal_quorum.cli import app


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
