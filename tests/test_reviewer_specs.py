from __future__ import annotations

import sys
from dataclasses import replace

import pytest

from krystal_quorum.diversity import analyze_reviewer_objects
from krystal_quorum.reviewer_specs import (
    DataBoundary,
    build_reviewers_from_specs,
    classify_endpoint,
    parse_reviewer_specs,
)


def test_loopback_and_lan_boundaries() -> None:
    assert classify_endpoint("http://127.0.0.1:11434") is DataBoundary.LOCAL
    assert classify_endpoint("http://127.9.8.7:11434") is DataBoundary.LOCAL
    assert classify_endpoint("http://[::1]:11434") is DataBoundary.LOCAL
    assert classify_endpoint("http://localhost:11434") is DataBoundary.LOCAL
    assert classify_endpoint("http://192.168.1.20:11434") is DataBoundary.EXTERNAL
    assert classify_endpoint("http://10.0.0.5:11434") is DataBoundary.EXTERNAL
    assert classify_endpoint("http://[::ffff:127.0.0.1]:11434") is DataBoundary.EXTERNAL


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:not-a-port",
        "ftp://127.0.0.1:11434",
        "127.0.0.1:11434",
        "http:127.0.0.1:11434",
        "http://",
        "http://[::1",
    ],
)
def test_malformed_or_non_http_loopback_urls_are_external(endpoint: str) -> None:
    assert classify_endpoint(endpoint) is DataBoundary.EXTERNAL


def test_credential_bearing_loopback_url_is_local() -> None:
    assert classify_endpoint("http://user:password@127.0.0.1:11434") is DataBoundary.LOCAL


def test_parse_specs_classifies_backends_without_constructing_clients(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "krystal-quorum.toml"
    config.write_text(
        """
        [reviewers.local-codex]
        type = "command"
        command = ["placeholder"]
        family = "codex"
        data_boundary = "local"
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    specs = parse_reviewer_specs(
        "mock,ollama:qwen2.5:14b,openai:gpt-4.1,command:local-codex,hosted:reviewer",
        config_path=config,
    )

    assert [(spec.reviewer_id, spec.family, spec.data_boundary) for spec in specs] == [
        ("mock", "mock", DataBoundary.LOCAL),
        ("ollama:qwen2.5:14b", "qwen2.5", DataBoundary.LOCAL),
        ("openai:gpt-4.1", "gpt-4.1", DataBoundary.EXTERNAL),
        ("command:local-codex", "codex", DataBoundary.LOCAL),
        ("hosted:reviewer", "reviewer", DataBoundary.EXTERNAL),
    ]
    assert specs[3].command == ("placeholder",)


def test_cloud_tagged_ollama_is_external_even_on_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    spec = parse_reviewer_specs("ollama:qwen3:cloud")[0]

    assert spec.data_boundary is DataBoundary.EXTERNAL


def test_command_without_boundary_is_unknown(tmp_path) -> None:
    config = tmp_path / "krystal-quorum.toml"
    config.write_text(
        f"""
        [reviewers.local-codex]
        type = "command"
        command = [{sys.executable!r}]
        """,
        encoding="utf-8",
    )

    spec = parse_reviewer_specs("command:local-codex", config_path=config)[0]

    assert spec.data_boundary is DataBoundary.UNKNOWN


def test_command_rejects_invalid_boundary_value(tmp_path) -> None:
    config = tmp_path / "krystal-quorum.toml"
    config.write_text(
        """
        [reviewers.local-codex]
        type = "command"
        command = ["placeholder"]
        data_boundary = "lan"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="data_boundary"):
        parse_reviewer_specs("command:local-codex", config_path=config)


def test_all_constructed_reviewers_keep_their_parsed_family_for_diversity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "krystal-quorum.toml"
    config.write_text(
        """
        [reviewers.local-codex]
        type = "command"
        command = ["placeholder"]
        family = "local-codex"
        data_boundary = "local"
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11435/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    specs = parse_reviewer_specs(
        "mock,ollama:qwen2.5:14b,openai:gpt-4.1,command:local-codex",
        config_path=config,
    )
    specs = [replace(spec, family=f"normalized-{index}") for index, spec in enumerate(specs)]

    reviewers = build_reviewers_from_specs(specs)
    report = analyze_reviewer_objects(reviewers)

    assert [reviewer.family for reviewer in reviewers] == [spec.family for spec in specs]
    assert [item.family for item in report.reviewers] == [spec.family for spec in specs]
