from __future__ import annotations

import os

from krystal_quorum.reviewers.base import ReviewerProtocol
from krystal_quorum.reviewers.mock import MockReviewer
from krystal_quorum.reviewers.ollama import OllamaReviewer
from krystal_quorum.reviewers.openai_compatible import OpenAICompatibleReviewer


def build_reviewers(reviewer_names: str) -> list[ReviewerProtocol]:
    reviewers: list[ReviewerProtocol] = []
    for raw_name in reviewer_names.split(","):
        name = raw_name.strip().lower()
        if not name:
            continue
        if name == "mock":
            reviewers.append(MockReviewer())
            continue
        if name.startswith("ollama:"):
            model = raw_name.split(":", 1)[1].strip()
            reviewers.append(
                OllamaReviewer(
                    reviewer_id=f"ollama:{model}",
                    model=model,
                    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                )
            )
            continue
        if name.startswith("openai:"):
            model = raw_name.split(":", 1)[1].strip()
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key:
                raise ValueError("OPENAI_API_KEY is required for openai reviewers")
            reviewers.append(
                OpenAICompatibleReviewer(
                    reviewer_id=f"openai:{model}",
                    model=model,
                    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                    api_key=api_key,
                )
            )
            continue
        raise ValueError(f"unknown reviewer: {raw_name}")
    if not reviewers:
        reviewers.append(MockReviewer())
    return reviewers
