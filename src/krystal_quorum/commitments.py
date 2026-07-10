"""Deterministic extraction of required plan commitments."""

from dataclasses import dataclass
from enum import Enum
import re


class CommitmentCategory(str, Enum):
    """The recognized plan sections that contain required commitments."""

    ACCEPTANCE = "acceptance"
    SCOPE = "scope"
    TESTS = "tests"
    ROLLBACK = "rollback"
    SECURITY = "security"
    DEPENDENCIES = "dependencies"
    OBSERVABILITY = "observability"


@dataclass(frozen=True)
class Commitment:
    """A single promise extracted from a recognized plan section."""

    id: str
    category: CommitmentCategory
    text: str
    source_line: int
    group: str | None


class CommitmentError(ValueError):
    """Raised when explicit commitment IDs make a plan invalid."""


BRACKET_ID = re.compile(r"^\[(AC|SCOPE|TEST|RB|SEC|DEP|OBS)-([1-9][0-9]*)\]\s+", re.I)
COLON_ID = re.compile(r"^(AC|SCOPE|TEST|RB|SEC|DEP|OBS)-([1-9][0-9]*):\s+", re.I)


_CATEGORY_PREFIXES = {
    CommitmentCategory.ACCEPTANCE: "AC",
    CommitmentCategory.SCOPE: "SCOPE",
    CommitmentCategory.TESTS: "TEST",
    CommitmentCategory.ROLLBACK: "RB",
    CommitmentCategory.SECURITY: "SEC",
    CommitmentCategory.DEPENDENCIES: "DEP",
    CommitmentCategory.OBSERVABILITY: "OBS",
}

_HEADING_ALIASES = {
    "acceptance": CommitmentCategory.ACCEPTANCE,
    "acceptance criteria": CommitmentCategory.ACCEPTANCE,
    "success criteria": CommitmentCategory.ACCEPTANCE,
    "definition of done": CommitmentCategory.ACCEPTANCE,
    "scope": CommitmentCategory.SCOPE,
    "planned scope": CommitmentCategory.SCOPE,
    "implementation scope": CommitmentCategory.SCOPE,
    "implementation map": CommitmentCategory.SCOPE,
    "files": CommitmentCategory.SCOPE,
    "files to change": CommitmentCategory.SCOPE,
    "files and modules": CommitmentCategory.SCOPE,
    "files or modules expected to change": CommitmentCategory.SCOPE,
    "tests": CommitmentCategory.TESTS,
    "testing": CommitmentCategory.TESTS,
    "test plan": CommitmentCategory.TESTS,
    "test strategy": CommitmentCategory.TESTS,
    "verification": CommitmentCategory.TESTS,
    "verification plan": CommitmentCategory.TESTS,
    "tests and verification": CommitmentCategory.TESTS,
    "rollback": CommitmentCategory.ROLLBACK,
    "rollback plan": CommitmentCategory.ROLLBACK,
    "recovery plan": CommitmentCategory.ROLLBACK,
    "security": CommitmentCategory.SECURITY,
    "safety": CommitmentCategory.SECURITY,
    "security and safety": CommitmentCategory.SECURITY,
    "dependencies": CommitmentCategory.DEPENDENCIES,
    "migrations": CommitmentCategory.DEPENDENCIES,
    "dependencies and migrations": CommitmentCategory.DEPENDENCIES,
    "observability": CommitmentCategory.OBSERVABILITY,
    "monitoring": CommitmentCategory.OBSERVABILITY,
    "telemetry": CommitmentCategory.OBSERVABILITY,
}

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+[ \t]*)?$")
_FENCE_OPEN = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,}).*$")
_LIST_ITEM = re.compile(
    r"^(?P<indent> *)(?:[-+*][ \t]+\[[ xX]\][ \t]+|[-+*][ \t]+|\d+[.)][ \t]+)(?P<body>.*)$"
)


@dataclass(frozen=True)
class _Heading:
    level: int
    title: str
    category: CommitmentCategory | None


@dataclass
class _PendingCommitment:
    category: CommitmentCategory
    text_lines: list[str]
    source_line: int
    group: str | None
    explicit_id: str | None
    list_indent: int | None


@dataclass(frozen=True)
class _Fence:
    marker: str
    length: int
    is_continuation: bool


@dataclass(frozen=True)
class _ListItem:
    indent: int
    text: str


def _normalize_heading(text: str) -> str:
    normalized = text.strip()
    if normalized.endswith(":"):
        normalized = normalized[:-1].strip()
    return " ".join(normalized.lower().split())


def _group_title(text: str) -> str:
    title = text.strip()
    if title.endswith(":"):
        title = title[:-1].strip()
    return " ".join(title.split())


def _list_item(line: str) -> _ListItem | None:
    match = _LIST_ITEM.match(line)
    if not match:
        return None
    return _ListItem(indent=len(match.group("indent")), text=match.group("body"))


def _fence_opener(line: str, is_continuation: bool) -> _Fence | None:
    match = _FENCE_OPEN.match(line)
    if not match:
        return None
    marker = match.group("marker")
    return _Fence(marker=marker[0], length=len(marker), is_continuation=is_continuation)


def _is_fence_closer(line: str, fence: _Fence) -> bool:
    return re.fullmatch(rf" {{0,3}}{re.escape(fence.marker)}{{{fence.length},}}[ \t]*", line) is not None


def _parse_explicit_id(text: str) -> tuple[str | None, str]:
    match = BRACKET_ID.match(text) or COLON_ID.match(text)
    if not match:
        return None, text
    return f"{match.group(1).upper()}-{match.group(2)}", text[match.end() :]


def _commit_pending(
    pending: _PendingCommitment | None,
    commitments: list[_PendingCommitment],
) -> None:
    if pending is not None:
        commitments.append(pending)


def _append_continuation(
    pending: _PendingCommitment,
    blank_lines: list[str],
    line: str,
) -> None:
    pending.text_lines.extend(blank_lines)
    blank_lines.clear()
    pending.text_lines.append(line)


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def extract_commitments(plan_text: str) -> list[Commitment]:
    """Extract commitments from exact recognized Markdown ATX-heading sections."""
    lines = plan_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    headings: list[_Heading] = []
    pending: _PendingCommitment | None = None
    extracted: list[_PendingCommitment] = []
    explicit_ids: set[str] = set()
    pending_blank_lines: list[str] = []
    fence: _Fence | None = None

    for line_number, line in enumerate(lines, start=1):
        if fence is not None:
            if pending is not None and fence.is_continuation:
                _append_continuation(pending, pending_blank_lines, line)
            if _is_fence_closer(line, fence):
                fence = None
            continue

        fence_is_continuation = (
            pending is not None
            and pending.list_indent is not None
            and _line_indent(line) > pending.list_indent
        )
        opening_fence = _fence_opener(line, fence_is_continuation)
        if opening_fence is not None:
            if pending is not None and fence_is_continuation:
                _append_continuation(pending, pending_blank_lines, line)
            elif pending is not None:
                pending_blank_lines.clear()
                pending.list_indent = None
            fence = opening_fence
            continue

        heading_match = _HEADING.match(line)
        if heading_match:
            _commit_pending(pending, extracted)
            pending = None
            pending_blank_lines.clear()

            level = len(heading_match.group(1))
            while headings and headings[-1].level >= level:
                headings.pop()

            heading_text = heading_match.group(2)
            headings.append(
                _Heading(
                    level=level,
                    title=_group_title(heading_text),
                    category=_HEADING_ALIASES.get(_normalize_heading(heading_text)),
                )
            )
            continue

        list_item = _list_item(line)
        active_index = next(
            (
                index
                for index in range(len(headings) - 1, -1, -1)
                if headings[index].category is not None
            ),
            None,
        )

        if list_item is not None and list_item.indent <= 3 and (
            pending is None
            or pending.list_indent is None
            or list_item.indent <= pending.list_indent
        ):
            _commit_pending(pending, extracted)
            pending = None
            pending_blank_lines.clear()
            if active_index is None:
                continue

            active_heading = headings[active_index]
            explicit_id, text = _parse_explicit_id(list_item.text)
            if explicit_id is not None:
                expected_prefix = _CATEGORY_PREFIXES[active_heading.category]
                if not explicit_id.startswith(f"{expected_prefix}-"):
                    raise CommitmentError(
                        f"commitment ID {explicit_id} does not match "
                        f"{active_heading.category.value} category"
                    )
                if explicit_id in explicit_ids:
                    raise CommitmentError(f"duplicate explicit commitment ID: {explicit_id}")
                explicit_ids.add(explicit_id)

            group_titles = [heading.title for heading in headings[active_index + 1 :]]
            pending = _PendingCommitment(
                category=active_heading.category,
                text_lines=[text],
                source_line=line_number,
                group=" > ".join(group_titles) if group_titles else None,
                explicit_id=explicit_id,
                list_indent=list_item.indent,
            )
        elif pending is not None and list_item is not None and pending.list_indent is not None:
            _append_continuation(pending, pending_blank_lines, line)
        elif pending is not None and not line.strip():
            pending_blank_lines.append(line)
        elif pending is not None and pending.list_indent is not None:
            if _line_indent(line) > pending.list_indent:
                _append_continuation(pending, pending_blank_lines, line)
            else:
                pending_blank_lines.clear()
                pending.list_indent = None

    _commit_pending(pending, extracted)

    generated_numbers = {category: 1 for category in CommitmentCategory}
    commitments: list[Commitment] = []
    assigned_ids = set(explicit_ids)
    for item in extracted:
        commitment_id = item.explicit_id
        if commitment_id is None:
            prefix = _CATEGORY_PREFIXES[item.category]
            number = generated_numbers[item.category]
            commitment_id = f"{prefix}-{number}"
            while commitment_id in assigned_ids:
                number += 1
                commitment_id = f"{prefix}-{number}"
            generated_numbers[item.category] = number + 1
            assigned_ids.add(commitment_id)

        commitments.append(
            Commitment(
                id=commitment_id,
                category=item.category,
                text="\n".join(item.text_lines),
                source_line=item.source_line,
                group=item.group,
            )
        )

    return commitments
