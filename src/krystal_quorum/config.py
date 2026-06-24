from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from krystal_quorum.reviewers.base import ReviewerProtocol
from krystal_quorum.reviewers.command import CommandReviewer
from krystal_quorum.reviewers.mock import MockReviewer
from krystal_quorum.reviewers.ollama import OllamaReviewer
from krystal_quorum.reviewers.openai_compatible import OpenAICompatibleReviewer


def build_reviewers(
    reviewer_names: str,
    *,
    config_path: Path | None = None,
) -> list[ReviewerProtocol]:
    config = _load_config(config_path)
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
            ollama_options = _ollama_options(config)
            reviewers.append(
                OllamaReviewer(
                    reviewer_id=f"ollama:{model}",
                    model=model,
                    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                    think=_optional_bool(ollama_options.get("think"), "ollama.think"),
                    options=ollama_options.get("options"),
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
        if name.startswith("command:"):
            reviewer_name = raw_name.split(":", 1)[1].strip()
            reviewers.append(_build_command_reviewer(reviewer_name, config, config_path))
            continue
        raise ValueError(f"unknown reviewer: {raw_name}")
    if not reviewers:
        reviewers.append(MockReviewer())
    return reviewers


def _load_config(config_path: Path | None) -> dict[str, Any]:
    if config_path is None:
        return {}
    try:
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"could not read config {config_path}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def _build_command_reviewer(
    name: str,
    config: dict[str, Any],
    config_path: Path | None,
) -> CommandReviewer:
    if config_path is None:
        raise ValueError(f"command reviewer requires --config: command:{name}")
    reviewer_configs = config.get("reviewers")
    if not isinstance(reviewer_configs, dict):
        raise ValueError("config must contain a [reviewers] table")
    reviewer_config = reviewer_configs.get(name)
    if not isinstance(reviewer_config, dict):
        raise ValueError(f"command reviewer not found in config: command:{name}")
    if reviewer_config.get("type") != "command":
        raise ValueError(f"reviewer command:{name} must have type = \"command\"")
    command = reviewer_config.get("command")
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        raise ValueError(f"reviewer command:{name} must define command as a string array")

    base_dir = config_path.resolve().parent
    cwd = _optional_path(reviewer_config.get("cwd"), base_dir)
    path_base = cwd or base_dir
    output_file = _optional_path(reviewer_config.get("output_file"), path_base)
    env = reviewer_config.get("env")
    if env is not None and not (
        isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
    ):
        raise ValueError(f"reviewer command:{name} env must be a string table")

    return CommandReviewer(
        reviewer_id=f"command:{name}",
        command=command,
        cwd=cwd,
        env=env,
        output_file=output_file,
        timeout_s=_optional_number(reviewer_config.get("timeout_s"), "timeout_s"),
        wait_for_output_s=_optional_number(
            reviewer_config.get("wait_for_output_s"),
            "wait_for_output_s",
            default=0.0,
        ),
        family=_optional_string(reviewer_config.get("family"), "family"),
    )


def _ollama_options(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("ollama")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("ollama config must be a table")

    options: dict[str, Any] = {}
    num_predict = raw.get("num_predict")
    if num_predict is not None:
        options["num_predict"] = _optional_int(num_predict, "ollama.num_predict")

    raw_options = raw.get("options")
    if raw_options is not None:
        if not isinstance(raw_options, dict):
            raise ValueError("ollama.options must be a table")
        for key, value in raw_options.items():
            if not isinstance(key, str):
                raise ValueError("ollama.options keys must be strings")
            if not isinstance(value, str | int | float | bool):
                raise ValueError(f"ollama.options.{key} must be a scalar value")
            options[key] = value

    return {
        "think": raw.get("think"),
        "options": options,
    }


def _optional_path(value: Any, base_dir: Path) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("path config values must be strings")
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _optional_number(value: Any, name: str, default: float | None = None) -> float | None:
    if value is None:
        return default
    if not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _optional_int(value: Any, name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_bool(value: Any, name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value
