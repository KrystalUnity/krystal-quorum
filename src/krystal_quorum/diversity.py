from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from krystal_quorum.models import DiversityReport, ReviewerFamily


MODEL_TAGS = {"cloud", "latest"}
PROFILE_SUFFIXES = ("mini", "nano", "turbo", "pro", "instruct", "it", "preview", "gguf")


def reviewer_family(reviewer_id: str, *, family_override: str | None = None) -> ReviewerFamily:
    backend, raw_family = _split_reviewer_id(reviewer_id)
    family = (
        _normalize_family(family_override)
        if family_override
        else _normalize_model_family(raw_family)
        if backend in {"ollama", "openai"}
        else _normalize_family(raw_family)
    )
    return ReviewerFamily(reviewer=reviewer_id, backend=backend, family=family)


def reviewer_family_from_object(reviewer: Any) -> ReviewerFamily:
    reviewer_id = str(getattr(reviewer, "id", "unknown"))
    family_override = getattr(reviewer, "family", None)
    return reviewer_family(
        reviewer_id,
        family_override=family_override if isinstance(family_override, str) else None,
    )


def analyze_reviewer_diversity(reviewer_ids: Sequence[str]) -> DiversityReport:
    return _build_report([reviewer_family(reviewer_id) for reviewer_id in reviewer_ids])


def analyze_reviewer_objects(reviewers: Sequence[Any]) -> DiversityReport:
    return _build_report([reviewer_family_from_object(reviewer) for reviewer in reviewers])


def _build_report(reviewers: list[ReviewerFamily]) -> DiversityReport:
    by_family: dict[str, list[str]] = defaultdict(list)
    for reviewer in reviewers:
        by_family[reviewer.family].append(reviewer.reviewer)

    shared = {family: ids for family, ids in by_family.items() if len(ids) >= 2}
    if shared:
        family, ids = sorted(shared.items())[0]
        return DiversityReport(
            status="low",
            reviewers=reviewers,
            reason=f"shared family {family}: {', '.join(ids)}",
        )
    return DiversityReport(status="ok", reviewers=reviewers)


def _split_reviewer_id(reviewer_id: str) -> tuple[str, str]:
    if ":" not in reviewer_id:
        return reviewer_id.lower() or "unknown", reviewer_id
    backend, raw_family = reviewer_id.split(":", 1)
    return backend.lower() or "unknown", raw_family


def _normalize_model_family(raw_family: str) -> str:
    family = _normalize_family(raw_family)
    family = family.rsplit("/", 1)[-1]

    parts = family.split(":")
    if len(parts) > 1 and (parts[-1] in MODEL_TAGS or _is_size_tag(parts[-1])):
        family = ":".join(parts[:-1])

    family = re.sub(r"-\d+(?:\.\d+)?b(?:-.+)?$", "", family)
    for suffix in PROFILE_SUFFIXES:
        family = re.sub(rf"-{suffix}$", "", family)
    return family or "unknown"


def _normalize_family(raw_family: str) -> str:
    family = raw_family.strip().lower()
    family = re.sub(r"\s+", "-", family)
    family = family.strip("-_:")
    return family or "unknown"


def _is_size_tag(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?b", value))
