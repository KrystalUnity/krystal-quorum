from pathlib import Path

import pytest
from typer.testing import CliRunner

from krystal_quorum.cli import app


@pytest.mark.parametrize(
    ("target", "expected_files"),
    [
        (
            "claude-code",
            [
                ".claude/skills/krystal-quorum-review/SKILL.md",
                ".claude/commands/quorum-review.md",
            ],
        ),
        ("hermes", [".hermes/skills/krystal-quorum-plan-review/SKILL.md"]),
        ("codex", [".codex/skills/krystal-quorum-review/SKILL.md"]),
        ("claw", [".openclaw/skills/krystal-quorum-openclaw-review/SKILL.md"]),
        ("openclaw", [".openclaw/skills/krystal-quorum-openclaw-review/SKILL.md"]),
        ("opencode", [".opencode/skills/krystal-quorum-review.md"]),
    ],
)
def test_init_command_installs_agent_templates(
    tmp_path: Path, target: str, expected_files: list[str]
) -> None:
    result = CliRunner().invoke(app, ["init", "--target", target, "--path", str(tmp_path)])

    assert result.exit_code == 0
    shared = tmp_path / ".krystal-quorum" / "agents" / "quorum-review.md"
    assert shared.exists()
    assert "Krystal Quorum Agent Review Gate" in shared.read_text(encoding="utf-8")
    for expected_file in expected_files:
        installed = tmp_path / expected_file
        assert installed.exists()
        assert "Krystal Quorum" in installed.read_text(encoding="utf-8")
    assert f"Installed {target}" in result.output


def test_init_command_lists_supported_targets() -> None:
    result = CliRunner().invoke(app, ["init", "--list-targets"])

    assert result.exit_code == 0
    for target in ["claude-code", "codex", "hermes", "claw", "openclaw", "opencode", "all"]:
        assert target in result.output


def test_init_command_installs_all_targets(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["init", "--target", "all", "--path", str(tmp_path)])

    assert result.exit_code == 0
    for expected_file in [
        ".claude/skills/krystal-quorum-review/SKILL.md",
        ".codex/skills/krystal-quorum-review/SKILL.md",
        ".hermes/skills/krystal-quorum-plan-review/SKILL.md",
        ".openclaw/skills/krystal-quorum-openclaw-review/SKILL.md",
        ".opencode/skills/krystal-quorum-review.md",
    ]:
        assert (tmp_path / expected_file).exists()
    assert "Installed all" in result.output


def test_init_command_all_reports_shared_workflow_once(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["init", "--target", "all", "--path", str(tmp_path)])

    assert result.exit_code == 0
    assert result.output.count(".krystal-quorum") == 1


def test_init_command_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    existing = tmp_path / ".hermes" / "skills" / "krystal-quorum-plan-review" / "SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("custom local workflow", encoding="utf-8")

    result = CliRunner().invoke(app, ["init", "--target", "hermes", "--path", str(tmp_path)])

    assert result.exit_code == 3
    assert "already exists" in result.output
    assert existing.read_text(encoding="utf-8") == "custom local workflow"


def test_init_command_force_overwrites_existing_template(tmp_path: Path) -> None:
    existing = tmp_path / ".hermes" / "skills" / "krystal-quorum-plan-review" / "SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("custom local workflow", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["init", "--target", "hermes", "--path", str(tmp_path), "--force"],
    )

    assert result.exit_code == 0
    assert "custom local workflow" not in existing.read_text(encoding="utf-8")
