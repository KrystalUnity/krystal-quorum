from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


class InitError(ValueError):
    """Raised when an integration template cannot be installed safely."""


@dataclass(frozen=True)
class TemplateFile:
    source: str
    destination: str


TARGET_TEMPLATES: dict[str, tuple[TemplateFile, ...]] = {
    "claude-code": (
        TemplateFile(
            source="claude-code/.claude/skills/krystal-quorum-review/SKILL.md",
            destination=".claude/skills/krystal-quorum-review/SKILL.md",
        ),
        TemplateFile(
            source="claude-code/.claude/commands/quorum-review.md",
            destination=".claude/commands/quorum-review.md",
        ),
    ),
    "hermes": (
        TemplateFile(
            source="hermes/.hermes/skills/krystal-quorum-plan-review/SKILL.md",
            destination=".hermes/skills/krystal-quorum-plan-review/SKILL.md",
        ),
    ),
    "openclaw": (
        TemplateFile(
            source="openclaw/.openclaw/skills/krystal-quorum-openclaw-review/SKILL.md",
            destination=".openclaw/skills/krystal-quorum-openclaw-review/SKILL.md",
        ),
    ),
}


def install_integration_templates(target: str, root: Path, *, force: bool = False) -> list[Path]:
    """Install bundled agent integration templates under root."""
    if target not in TARGET_TEMPLATES:
        available = ", ".join(sorted(TARGET_TEMPLATES))
        raise InitError(f"Unknown init target '{target}'. Available targets: {available}")

    root.mkdir(parents=True, exist_ok=True)
    root_resolved = root.resolve()
    template_root = files("krystal_quorum").joinpath("templates", "agent_integrations")
    planned: list[tuple[Path, str]] = []

    for template in TARGET_TEMPLATES[target]:
        destination = root / template.destination
        destination_resolved = destination.resolve()
        if not destination_resolved.is_relative_to(root_resolved):
            raise InitError(f"Refusing to write outside --path: {destination}")
        if destination.exists() and not force:
            raise InitError(f"File already exists; use --force to overwrite: {destination}")
        source = template_root.joinpath(*template.source.split("/"))
        planned.append((destination, source.read_text(encoding="utf-8")))

    installed: list[Path] = []
    for destination, content in planned:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        installed.append(destination)

    return installed
