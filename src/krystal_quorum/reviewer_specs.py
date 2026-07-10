from __future__ import annotations

import ipaddress
import os
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from krystal_quorum.diversity import reviewer_family
from krystal_quorum.reviewers.base import ReviewerProtocol
from krystal_quorum.reviewers.command import CommandReviewer
from krystal_quorum.reviewers.mock import MockReviewer
from krystal_quorum.reviewers.ollama import OllamaReviewer
from krystal_quorum.reviewers.openai_compatible import OpenAICompatibleReviewer


class DataBoundary(StrEnum):
    LOCAL = "local"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReviewerSpec:
    reviewer_id: str
    backend: str
    family: str
    endpoint: str | None
    data_boundary: DataBoundary
    model: str | None = None
    command: tuple[str, ...] | None = None
    cwd: Path | None = None
    env: dict[str, str] | None = None
    output_file: Path | None = None
    timeout_s: float | None = None
    wait_for_output_s: float = 0.0
    ollama_think: bool | None = None
    ollama_options: dict[str, Any] | None = None


def parse_reviewer_specs(
    reviewer_names: str,
    *,
    config_path: Path | None = None,
) -> list[ReviewerSpec]:
    config = _load_config(config_path)
    specs: list[ReviewerSpec] = []
    for raw_name in reviewer_names.split(","):
        raw_name = raw_name.strip()
        name = raw_name.lower()
        if not name:
            continue
        if name == "mock":
            specs.append(_simple_spec("mock", "mock", DataBoundary.LOCAL))
        elif name.startswith("ollama:"):
            model = raw_name.split(":", 1)[1].strip()
            reviewer_id = f"ollama:{model}"
            endpoint = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            boundary = (
                DataBoundary.EXTERNAL
                if _is_cloud_tagged_ollama(model)
                else classify_endpoint(endpoint)
            )
            options = _ollama_options(config)
            specs.append(
                ReviewerSpec(
                    reviewer_id=reviewer_id,
                    backend="ollama",
                    family=reviewer_family(reviewer_id).family,
                    endpoint=endpoint,
                    data_boundary=boundary,
                    model=model,
                    ollama_think=_optional_bool(options.get("think"), "ollama.think"),
                    ollama_options=options.get("options"),
                )
            )
        elif name.startswith("openai:"):
            model = raw_name.split(":", 1)[1].strip()
            reviewer_id = f"openai:{model}"
            endpoint = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            specs.append(
                ReviewerSpec(
                    reviewer_id=reviewer_id,
                    backend="openai",
                    family=reviewer_family(reviewer_id).family,
                    endpoint=endpoint,
                    data_boundary=classify_endpoint(endpoint),
                    model=model,
                )
            )
        elif name.startswith("command:"):
            specs.append(_parse_command_spec(raw_name.split(":", 1)[1].strip(), config, config_path))
        elif name.startswith("hosted:"):
            reviewer_id = f"hosted:{raw_name.split(':', 1)[1].strip()}"
            specs.append(_simple_spec(reviewer_id, "hosted", DataBoundary.EXTERNAL))
        else:
            raise ValueError(f"unknown reviewer: {raw_name}")
    return specs or [_simple_spec("mock", "mock", DataBoundary.LOCAL)]


def build_reviewers_from_specs(specs: list[ReviewerSpec]) -> list[ReviewerProtocol]:
    reviewers: list[ReviewerProtocol] = []
    for spec in specs:
        if spec.backend == "mock":
            reviewer: ReviewerProtocol = MockReviewer()
        elif spec.backend == "ollama":
            reviewer = OllamaReviewer(
                reviewer_id=spec.reviewer_id,
                model=_required(spec.model, spec.reviewer_id),
                base_url=_required(spec.endpoint, spec.reviewer_id),
                think=spec.ollama_think,
                options=spec.ollama_options,
            )
        elif spec.backend == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key:
                raise ValueError("OPENAI_API_KEY is required for openai reviewers")
            reviewer = OpenAICompatibleReviewer(
                reviewer_id=spec.reviewer_id,
                model=_required(spec.model, spec.reviewer_id),
                base_url=_required(spec.endpoint, spec.reviewer_id),
                api_key=api_key,
            )
        elif spec.backend == "command":
            reviewer = CommandReviewer(
                reviewer_id=spec.reviewer_id,
                command=spec.command or (),
                cwd=spec.cwd,
                env=spec.env,
                output_file=spec.output_file,
                timeout_s=spec.timeout_s,
                wait_for_output_s=spec.wait_for_output_s,
                family=spec.family,
            )
        else:
            raise ValueError(f"unknown reviewer: {spec.reviewer_id}")
        setattr(reviewer, "family", spec.family)
        reviewers.append(reviewer)
    return reviewers


def classify_endpoint(endpoint: str) -> DataBoundary:
    try:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return DataBoundary.EXTERNAL
        host = parsed.hostname
        parsed.port
    except ValueError:
        return DataBoundary.EXTERNAL
    if host is None:
        return DataBoundary.EXTERNAL
    if host.lower() == "localhost":
        return DataBoundary.LOCAL
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return DataBoundary.EXTERNAL
    if isinstance(address, ipaddress.IPv4Address) and address.packed[0] == 127:
        return DataBoundary.LOCAL
    if isinstance(address, ipaddress.IPv6Address) and address == ipaddress.IPv6Address("::1"):
        return DataBoundary.LOCAL
    return DataBoundary.EXTERNAL


def _simple_spec(reviewer_id: str, backend: str, boundary: DataBoundary) -> ReviewerSpec:
    return ReviewerSpec(
        reviewer_id=reviewer_id,
        backend=backend,
        family=reviewer_family(reviewer_id).family,
        endpoint=None,
        data_boundary=boundary,
    )


def _parse_command_spec(
    name: str,
    config: dict[str, Any],
    config_path: Path | None,
) -> ReviewerSpec:
    if config_path is None:
        raise ValueError(f"command reviewer requires --config: command:{name}")
    reviewer_configs = config.get("reviewers")
    if not isinstance(reviewer_configs, dict):
        raise ValueError("config must contain a [reviewers] table")
    reviewer_config = reviewer_configs.get(name)
    if not isinstance(reviewer_config, dict):
        raise ValueError(f"command reviewer not found in config: command:{name}")
    if reviewer_config.get("type") != "command":
        raise ValueError(f'reviewer command:{name} must have type = "command"')
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
    family_override = _optional_string(reviewer_config.get("family"), "family")
    reviewer_id = f"command:{name}"

    return ReviewerSpec(
        reviewer_id=reviewer_id,
        backend="command",
        family=reviewer_family(reviewer_id, family_override=family_override).family,
        endpoint=None,
        data_boundary=_command_boundary(reviewer_config.get("data_boundary"), name),
        command=tuple(command),
        cwd=cwd,
        env=env,
        output_file=output_file,
        timeout_s=_optional_number(reviewer_config.get("timeout_s"), "timeout_s"),
        wait_for_output_s=_optional_number(
            reviewer_config.get("wait_for_output_s"),
            "wait_for_output_s",
            default=0.0,
        )
        or 0.0,
    )


def _command_boundary(value: Any, name: str) -> DataBoundary:
    if value is None:
        return DataBoundary.UNKNOWN
    if not isinstance(value, str) or value not in {"local", "external"}:
        raise ValueError(f"reviewer command:{name} data_boundary must be \"local\" or \"external\"")
    return DataBoundary(value)


def _is_cloud_tagged_ollama(model: str) -> bool:
    return model.rsplit(":", 1)[-1].lower() == "cloud"


def _load_config(config_path: Path | None) -> dict[str, Any]:
    if config_path is None:
        return {}
    try:
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"could not read config {config_path}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


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

    return {"think": raw.get("think"), "options": options}


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


def _required(value: str | None, reviewer_id: str) -> str:
    if value is None:
        raise ValueError(f"reviewer {reviewer_id} is missing required construction data")
    return value
