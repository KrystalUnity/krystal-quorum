from __future__ import annotations

import json
from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_is_release_ready() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == "0.6.0"
    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["project"]["urls"]["Homepage"]
    assert pyproject["project"]["urls"]["Repository"]
    assert pyproject["tool"]["setuptools"]["package-data"]["krystal_quorum"] == [
        "templates/agent_integrations/common/quorum-review.md",
        "templates/agent_integrations/claude-code/.claude/commands/quorum-review.md",
        "templates/agent_integrations/claude-code/.claude/skills/krystal-quorum-review/SKILL.md",
        "templates/agent_integrations/codex/.codex/skills/krystal-quorum-review/SKILL.md",
        "templates/agent_integrations/hermes/.hermes/skills/krystal-quorum-plan-review/SKILL.md",
        "templates/agent_integrations/openclaw/.openclaw/skills/krystal-quorum-openclaw-review/SKILL.md",
        "templates/agent_integrations/opencode/.opencode/skills/krystal-quorum-review.md",
    ]
    assert "build>=1.2" in pyproject["project"]["optional-dependencies"]["dev"]
    assert "twine>=5" in pyproject["project"]["optional-dependencies"]["dev"]


def test_public_release_files_exist() -> None:
    for relative_path in [
        "CHANGELOG.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        "docs/architecture/consensus-matching.md",
        "docs/architecture/local-command-reviewers.md",
        "docs/agent-import-packs.md",
        "docs/prompts.md",
        "docs/demo.md",
        "docs/assets/quorum-demo.svg",
        "examples/good-plan.md",
        "examples/agent-plan.md",
        "benchmarks/README.md",
        "benchmarks/expected-findings.json",
        "benchmarks/fixtures/missing-acceptance.md",
        "benchmarks/fixtures/missing-rollback.md",
        "benchmarks/run_quorum_benchmark.py",
    ]:
        assert (REPO_ROOT / relative_path).exists(), relative_path


def test_internal_superpowers_plan_history_is_removed() -> None:
    plans_dir = REPO_ROOT / "docs" / "superpowers" / "plans"

    assert not plans_dir.exists()


def test_public_docs_do_not_reference_private_server_paths() -> None:
    forbidden = [
        "gex44",
        "krystal-unity-core/.env",
        "/root/krystal-quorum/data/spec_reviews",
        "OLLAMA_CLOUD_API_KEY",
    ]
    searchable = [
        *REPO_ROOT.glob("README.md"),
        *REPO_ROOT.glob("docs/**/*.md"),
        *REPO_ROOT.glob("integrations/**/*.md"),
        *REPO_ROOT.glob("integrations/**/*.toml"),
    ]

    for path in searchable:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in text, f"{phrase!r} leaked in {path.relative_to(REPO_ROOT)}"


def test_integration_toml_templates_parse() -> None:
    for path in (REPO_ROOT / "integrations" / "agent-templates").glob("*.toml"):
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        assert "reviewers" in parsed, path.name


def test_github_action_exposes_expected_inputs() -> None:
    action_text = (REPO_ROOT / "integrations" / "github-action" / "action.yml").read_text(
        encoding="utf-8"
    )

    for expected in [
        "package-spec:",
        "require-diversity:",
        "round2:",
        'default: "."',
        'krystal-quorum "${args[@]}"',
    ]:
        assert expected in action_text


def test_ci_tests_supported_python_versions() -> None:
    ci_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'python-version: ["3.11", "3.12"]' in ci_text


def test_security_doc_warns_command_reviewers_inherit_environment() -> None:
    security_text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "Command reviewers inherit the parent process environment" in security_text
    assert "allowlisted environment" in security_text


def test_benchmark_expected_findings_reference_existing_fixtures() -> None:
    expected_path = REPO_ROOT / "benchmarks" / "expected-findings.json"
    payload = json.loads(expected_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "1.0"
    assert len(payload["fixtures"]) >= 2
    for fixture in payload["fixtures"]:
        fixture_path = REPO_ROOT / "benchmarks" / "fixtures" / fixture["path"]
        assert fixture_path.exists(), fixture["path"]
        assert fixture["expected_topics"]
        assert fixture["description"]


def test_demo_examples_have_deterministic_mock_verdicts() -> None:
    bad_plan = (REPO_ROOT / "examples" / "bad-plan.md").read_text(encoding="utf-8")
    good_plan = (REPO_ROOT / "examples" / "good-plan.md").read_text(encoding="utf-8")

    assert "acceptance" not in bad_plan.lower()
    assert "acceptance" in good_plan.lower()
