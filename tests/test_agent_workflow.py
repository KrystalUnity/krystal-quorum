from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = REPO_ROOT / "src" / "krystal_quorum" / "templates" / "agent_integrations"
TARGET_SKILLS = [
    TEMPLATE_ROOT / "claude-code/.claude/skills/krystal-quorum-review/SKILL.md",
    TEMPLATE_ROOT / "claude-code/.claude/commands/quorum-review.md",
    TEMPLATE_ROOT / "codex/.codex/skills/krystal-quorum-review/SKILL.md",
    TEMPLATE_ROOT / "copilot/.github/skills/krystal-quorum-review/SKILL.md",
    TEMPLATE_ROOT / "hermes/.hermes/skills/krystal-quorum-plan-review/SKILL.md",
    TEMPLATE_ROOT / "openclaw/.openclaw/skills/krystal-quorum-openclaw-review/SKILL.md",
    TEMPLATE_ROOT / "opencode/.opencode/skills/krystal-quorum-review.md",
]


def test_bundled_workflow_requires_the_verified_two_gate_path() -> None:
    workflow = (TEMPLATE_ROOT / "common/quorum-review.md").read_text(encoding="utf-8")

    for expected in [
        "before editing code",
        "recognized commitment sections",
        "configured real reviewers",
        "ask the human once",
        "--bind-repo .",
        "approval.json",
        "approved scope",
        "normal tests",
        "krystal-quorum diff",
        "--approval <approval.json>",
        "REVISE",
        "BLOCK",
        "Do not automatically commit",
        "push",
        "deploy",
        "policy automation",
        "hard enforcement boundary",
    ]:
        assert expected in workflow


def test_every_target_automatically_uses_the_shared_two_gate_workflow() -> None:
    for target_skill in TARGET_SKILLS:
        text = target_skill.read_text(encoding="utf-8")

        assert ".krystal-quorum/agents/quorum-review.md" in text, target_skill
        assert "automatically" in text.lower(), target_skill
        assert "non-trivial" in text.lower(), target_skill
        assert "policy automation" in text.lower(), target_skill
        assert "GitHub Action" in text, target_skill
        assert "hard enforcement" in text.lower(), target_skill
        assert "Do not automatically commit, push, or deploy" in text, target_skill


def test_copilot_skill_uses_project_skill_frontmatter_without_preapproved_tools() -> None:
    skill = (TEMPLATE_ROOT / "copilot/.github/skills/krystal-quorum-review/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert skill.startswith("---\nname: krystal-quorum-review\ndescription: ")
    assert "allowed-tools:" not in skill


def test_built_wheel_contains_every_agent_integration_file(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("krystal_quorum-0.7.0-*.whl"))

    with ZipFile(wheel) as archive:
        names = set(archive.namelist())

    for source in TEMPLATE_ROOT.rglob("*"):
        if source.is_file():
            package_path = source.relative_to(REPO_ROOT / "src").as_posix()
            assert package_path in names, package_path
