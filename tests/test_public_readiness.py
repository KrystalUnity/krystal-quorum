from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]


def _extract_h2_section(text: str, heading: str) -> str:
    section_match = re.search(
        rf"(?ms)^## {re.escape(heading)}\s+(.*?)(?=^## |\Z)",
        text,
    )
    assert section_match is not None
    return " ".join(section_match.group(1).split())


def _assert_section_contains_clauses_in_order(section: str, *clauses: str) -> None:
    search_start = 0
    for clause in clauses:
        found_at = section.find(clause, search_start)
        assert found_at != -1, f"Missing clause {clause!r} in section: {section}"
        search_start = found_at + len(clause)


def test_pyproject_is_release_ready() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == "0.7.0"
    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["project"]["urls"]["Homepage"]
    assert pyproject["project"]["urls"]["Repository"]
    assert pyproject["tool"]["setuptools"]["package-data"]["krystal_quorum"] == [
        "examples/bad-plan.md",
        "examples/good-plan.md",
        "templates/agent_integrations/common/quorum-review.md",
        "templates/agent_integrations/claude-code/.claude/commands/quorum-review.md",
        "templates/agent_integrations/claude-code/.claude/skills/krystal-quorum-review/SKILL.md",
        "templates/agent_integrations/codex/.codex/skills/krystal-quorum-review/SKILL.md",
        "templates/agent_integrations/copilot/.github/skills/krystal-quorum-review/SKILL.md",
        "templates/agent_integrations/hermes/.hermes/skills/krystal-quorum-plan-review/SKILL.md",
        "templates/agent_integrations/openclaw/.openclaw/skills/krystal-quorum-openclaw-review/SKILL.md",
        "templates/agent_integrations/opencode/.opencode/skills/krystal-quorum-review.md",
    ]
    assert "build>=1.2" in pyproject["project"]["optional-dependencies"]["dev"]
    assert "twine>=5" in pyproject["project"]["optional-dependencies"]["dev"]


def test_public_positioning_reflects_verified_two_gate_release() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    evidence_adr = (REPO_ROOT / "docs/architecture/plan-to-code-evidence.md").read_text(
        encoding="utf-8"
    )

    assert _extract_h2_section(evidence_adr, "Status") == "Implemented and verified in v0.7.0."
    description = pyproject["project"]["description"]
    assert description.startswith("Multi-AI two-gate")
    assert "implementation evidence" in description.lower()


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


def test_public_docs_advertise_pypi_install() -> None:
    for path in [
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "agent-integrations.md",
    ]:
        text = path.read_text(encoding="utf-8")
        assert "python -m pip install krystal-quorum" in text


def test_public_docs_explain_hosted_pack_rounds_and_pretty_output() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "--reviewers hosted:standard --api-token" in readme
    assert "--format pretty" in readme
    assert "Hosted packs choose their own reviewer mix and round strategy" in readme
    assert "No credits are charged" in readme


def test_github_action_docs_include_hosted_example() -> None:
    action_readme = (REPO_ROOT / "integrations" / "github-action" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "reviewers: hosted:quick" in action_readme
    assert "api-token: ${{ secrets.KU_TOKEN }}" in action_readme
    assert "output-dir" in action_readme
    assert "latest-output-dir" in action_readme


def test_github_action_docs_pin_the_current_release() -> None:
    action_readme = (REPO_ROOT / "integrations" / "github-action" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "v0.6.7" not in action_readme
    assert "krystal-quorum==0.6.7" not in action_readme
    assert "KrystalUnity/krystal-quorum@v0.7.0" in action_readme
    assert 'package-spec: "krystal-quorum==0.7.0"' in action_readme


def test_public_docs_explain_untracked_diff_input_policy() -> None:
    for relative_path in [
        "SECURITY.md",
        "docs/agent-import-packs.md",
        "docs/prompts.md",
    ]:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        normalized = " ".join(text.split())

        assert "eligible untracked files by default" in normalized, relative_path
        assert "persists them locally" in normalized, relative_path
        assert "--allow-untracked-external" in normalized, relative_path
        assert "--no-include-untracked" in normalized, relative_path


def test_readme_documents_exact_pr_sha_diff_action() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    for expected in [
        "fetch-depth: 0",
        "uses: KrystalUnity/krystal-quorum@v0.7.0",
        "mode: diff",
        "base: ${{ github.event.pull_request.base.sha }}",
        "head: ${{ github.event.pull_request.head.sha }}",
        'include-untracked: "false"',
        "package-spec: krystal-quorum==0.7.0",
        "summary-path",
        "unverified_reference",
    ]:
        assert expected in readme


def test_integration_toml_templates_parse() -> None:
    for path in (REPO_ROOT / "integrations" / "agent-templates").glob("*.toml"):
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        assert "reviewers" in parsed, path.name


def test_github_action_exposes_expected_inputs() -> None:
    action_text = (REPO_ROOT / "integrations" / "github-action" / "action.yml").read_text(
        encoding="utf-8"
    )

    for expected in [
        "api-token:",
        "api-base-url:",
        "outputs:",
        "latest-output-dir:",
        "package-spec:",
        "require-diversity:",
        "round2:",
        'default: "."',
        "mode:",
        "base:",
        "head:",
        "repo:",
        "summary-path:",
        "Mock reviewer only",
        "set +e",
        'krystal-quorum "${args[@]}"',
        'echo "output-dir=$INPUT_OUT_DIR" >> "$GITHUB_OUTPUT"',
        'exit "$code"',
    ]:
        assert expected in action_text


def test_root_github_action_is_marketplace_ready() -> None:
    action_text = (REPO_ROOT / "action.yml").read_text(encoding="utf-8")

    for expected in [
        "name: Krystal Quorum Multi-AI Plan Review",
        "author: Krystal Unity",
        "description: Run a multi-AI quorum review",
        "branding:",
        "icon: check-circle",
        "color: blue",
        "plan:",
        "reviewers:",
        "hosted:quick",
        "api-token:",
        "api-base-url:",
        "package-spec:",
        "default: krystal-quorum==0.7.0",
        "uses: actions/setup-python@v5",
        "mode:",
        "base:",
        "head:",
        "repo:",
        "Mock reviewer only",
        "set +e",
        'krystal-quorum "${args[@]}"',
        'echo "output-dir=$INPUT_OUT_DIR" >> "$GITHUB_OUTPUT"',
        "latest-output-dir:",
        "summary-path:",
        'exit "$code"',
    ]:
        assert expected in action_text


def test_ci_tests_supported_python_versions() -> None:
    ci_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'os: [ubuntu-latest, windows-latest]' in ci_text
    assert 'python-version: ["3.11", "3.12"]' in ci_text
    assert "macos-latest" in ci_text
    assert 'python-version: ["3.12"]' in ci_text


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


def test_plan_to_code_adr_defines_agent_native_execution_levels() -> None:
    text = (REPO_ROOT / "docs/architecture/plan-to-code-evidence.md").read_text("utf-8")
    section = _extract_h2_section(text, "Agent-Native Execution")

    _assert_section_contains_clauses_in_order(
        section,
        "`agent_policy`:",
        "author a commitment-bearing plan",
        "run bound review before edits",
        "handle `REVISE` by revising and rerunning until `APPROVE` or returning to the human",
        "implement",
        "run verified diff review",
        "present the final verdict/result",
    )
    _assert_section_contains_clauses_in_order(
        section,
        "After one-time `pip install krystal-quorum` and `krystal-quorum init --target ...`,",
        "ordinary non-trivial coding tasks should not require the human to type Quorum commands",
    )
    _assert_section_contains_clauses_in_order(
        section,
        "`ci_enforcement`:",
        "the GitHub Action is the hard enforcement boundary",
        "runs standalone diff review against exact PR SHAs",
        "can fail the check independently of agent behavior",
    )
    assert "Skill discovery is agent-controlled and is not a hard enforcement boundary" in section
