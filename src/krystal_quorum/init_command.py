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


COMMON_TEMPLATE = TemplateFile(
    source="common/quorum-review.md",
    destination=".krystal-quorum/agents/quorum-review.md",
)


@dataclass(frozen=True)
class TargetSpec:
    name: str
    description: str
    templates: tuple[TemplateFile, ...]


TARGET_SPECS: dict[str, TargetSpec] = {
    "claude-code": TargetSpec(
        name="claude-code",
        description="Claude Code skill and slash command",
        templates=(
            COMMON_TEMPLATE,
            TemplateFile(
                source="claude-code/.claude/skills/krystal-quorum-review/SKILL.md",
                destination=".claude/skills/krystal-quorum-review/SKILL.md",
            ),
            TemplateFile(
                source="claude-code/.claude/commands/quorum-review.md",
                destination=".claude/commands/quorum-review.md",
            ),
        ),
    ),
    "codex": TargetSpec(
        name="codex",
        description="Codex project-local skill",
        templates=(
            COMMON_TEMPLATE,
            TemplateFile(
                source="codex/.codex/skills/krystal-quorum-review/SKILL.md",
                destination=".codex/skills/krystal-quorum-review/SKILL.md",
            ),
        ),
    ),
    "hermes": TargetSpec(
        name="hermes",
        description="Hermes-style plan review skill",
        templates=(
            COMMON_TEMPLATE,
            TemplateFile(
                source="hermes/.hermes/skills/krystal-quorum-plan-review/SKILL.md",
                destination=".hermes/skills/krystal-quorum-plan-review/SKILL.md",
            ),
        ),
    ),
    "openclaw": TargetSpec(
        name="openclaw",
        description="OpenClaw/Claw pre-dispatch review skill",
        templates=(
            COMMON_TEMPLATE,
            TemplateFile(
                source="openclaw/.openclaw/skills/krystal-quorum-openclaw-review/SKILL.md",
                destination=".openclaw/skills/krystal-quorum-openclaw-review/SKILL.md",
            ),
        ),
    ),
    "opencode": TargetSpec(
        name="opencode",
        description="OpenCode-compatible review instruction",
        templates=(
            COMMON_TEMPLATE,
            TemplateFile(
                source="opencode/.opencode/skills/krystal-quorum-review.md",
                destination=".opencode/skills/krystal-quorum-review.md",
            ),
        ),
    ),
}

TARGET_ALIASES = {
    "claw": "openclaw",
}


def available_targets(*, include_all: bool = False) -> list[str]:
    targets = [*sorted(TARGET_SPECS), *sorted(TARGET_ALIASES)]
    if include_all:
        targets.append("all")
    return targets


def _canonical_target(target: str) -> str:
    normalized = target.strip().lower()
    return TARGET_ALIASES.get(normalized, normalized)


def _target_templates(target: str) -> tuple[TemplateFile, ...]:
    canonical = _canonical_target(target)
    if canonical not in TARGET_SPECS:
        available = ", ".join(available_targets(include_all=True))
        raise InitError(f"Unknown init target '{target}'. Available targets: {available}")
    return TARGET_SPECS[canonical].templates


def _targets_to_install(target: str) -> list[str]:
    canonical = _canonical_target(target)
    if canonical == "all":
        return sorted(TARGET_SPECS)
    if canonical not in TARGET_SPECS:
        available = ", ".join(available_targets(include_all=True))
        raise InitError(f"Unknown init target '{target}'. Available targets: {available}")
    return [canonical]


def install_integration_templates(target: str, root: Path, *, force: bool = False) -> list[Path]:
    """Install bundled agent integration templates under root."""
    root.mkdir(parents=True, exist_ok=True)
    root_resolved = root.resolve()
    template_root = files("krystal_quorum").joinpath("templates", "agent_integrations")
    planned: list[tuple[Path, str]] = []
    planned_destinations: set[Path] = set()

    for install_target in _targets_to_install(target):
        for template in _target_templates(install_target):
            destination = root / template.destination
            destination_resolved = destination.resolve()
            if destination_resolved in planned_destinations:
                continue
            if not destination_resolved.is_relative_to(root_resolved):
                raise InitError(f"Refusing to write outside --path: {destination}")
            if destination.exists() and not force:
                raise InitError(f"File already exists; use --force to overwrite: {destination}")
            source = template_root.joinpath(*template.source.split("/"))
            planned.append((destination, source.read_text(encoding="utf-8")))
            planned_destinations.add(destination_resolved)

    installed: list[Path] = []
    for destination, content in planned:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        installed.append(destination)

    return installed
