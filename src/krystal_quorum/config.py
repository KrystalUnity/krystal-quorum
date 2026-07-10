from __future__ import annotations

from pathlib import Path

from krystal_quorum.reviewer_specs import build_reviewers_from_specs, parse_reviewer_specs
from krystal_quorum.reviewers.base import ReviewerProtocol


def build_reviewers(
    reviewer_names: str,
    *,
    config_path: Path | None = None,
) -> list[ReviewerProtocol]:
    return build_reviewers_from_specs(parse_reviewer_specs(reviewer_names, config_path=config_path))
