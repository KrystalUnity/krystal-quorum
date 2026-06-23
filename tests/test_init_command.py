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
        ("openclaw", [".openclaw/skills/krystal-quorum-openclaw-review/SKILL.md"]),
    ],
)
def test_init_command_installs_agent_templates(
    tmp_path: Path, target: str, expected_files: list[str]
) -> None:
    result = CliRunner().invoke(app, ["init", "--target", target, "--path", str(tmp_path)])

    assert result.exit_code == 0
    for expected_file in expected_files:
        installed = tmp_path / expected_file
        assert installed.exists()
        assert "Krystal Quorum" in installed.read_text(encoding="utf-8")
    assert f"Installed {target}" in result.output


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
