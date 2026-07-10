from __future__ import annotations

import ast
import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_PATHS = [
    REPO_ROOT / "action.yml",
    REPO_ROOT / "integrations" / "github-action" / "action.yml",
]
COMMON_INPUTS = {
    "mode",
    "plan",
    "reviewers",
    "api-token",
    "api-base-url",
    "config",
    "out-dir",
    "round2",
    "require-diversity",
    "base",
    "head",
    "repo",
    "max-diff-chars",
    "max-review-chars",
    "context-lines",
    "include-untracked",
    "allow-untracked-external",
    "allow-secret-looking-input",
    "package-spec",
}
COMMON_DEFAULTS = {
    "mode": "review",
    "reviewers": "mock",
    "api-token": "",
    "api-base-url": "",
    "config": "",
    "out-dir": ".krystal-quorum/reviews",
    "round2": "false",
    "require-diversity": "false",
    "base": "",
    "head": "",
    "repo": ".",
    "max-diff-chars": "160000",
    "max-review-chars": "220000",
    "context-lines": "20",
    "include-untracked": "true",
    "allow-untracked-external": "false",
    "allow-secret-looking-input": "false",
}


def _parse_scalar(value: str) -> object:
    if value in {"true", "false"}:
        return value == "true"
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return ast.literal_eval(value)
    return value


def _parse_mapping_section(path: Path, section: str) -> dict[str, dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{section}:") + 1
    parsed: dict[str, dict[str, object]] = {}
    current: str | None = None

    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            current = line.strip()[:-1]
            parsed[current] = {}
            continue
        if current is not None and line.startswith("    ") and ":" in line:
            key, value = line.strip().split(":", 1)
            parsed[current][key] = _parse_scalar(value.strip())

    return parsed


def _run_script(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    step_start = lines.index("      id: run-quorum")
    block_start = lines.index("      run: |", step_start) + 1
    script: list[str] = []
    for line in lines[block_start:]:
        if line.startswith("      - name:"):
            break
        script.append(line[8:] if line.startswith("        ") else line)
    return "\n".join(script) + "\n"


def _find_bash() -> str:
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        if git_bash.exists():
            return str(git_bash)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required for the GitHub Action shell harness")
    return bash


def _write_fake_quorum(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
printf '%s\\0' "$@" > "$FAKE_ARGS_FILE"
if [ "$FAKE_CREATE_RUN" = "true" ]; then
  run_dir="$INPUT_OUT_DIR/run-$FAKE_EXIT_CODE"
  mkdir -p "$run_dir"
  printf '# Fake summary\\n\\nExit code %s.\\n' "$FAKE_EXIT_CODE" > "$run_dir/summary.md"
fi
exit "$FAKE_EXIT_CODE"
""",
        encoding="utf-8",
        newline="\n",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_action_shell(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    create_run: bool = True,
    mode: str = "diff",
    artifact_root_kind: str = "directory",
) -> tuple[subprocess.CompletedProcess[str], list[str], str, str]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_fake_quorum(fake_bin / "krystal-quorum")

    artifact_root = tmp_path / "artifacts"
    if artifact_root_kind == "directory":
        stale_dir = artifact_root / "stale-run"
        stale_dir.mkdir(parents=True)
        (stale_dir / "summary.md").write_text("# Stale summary\n", encoding="utf-8")
    elif artifact_root_kind == "file":
        artifact_root.write_text("not a directory\n", encoding="utf-8")
    elif artifact_root_kind == "unreadable":
        artifact_root.mkdir()
    else:
        raise ValueError(f"unknown artifact_root_kind: {artifact_root_kind}")

    github_output = tmp_path / "github-output.txt"
    step_summary = tmp_path / "step-summary.md"
    args_file = tmp_path / "args.bin"
    python_path = os.environ.get("PYTHONPATH", "")
    if artifact_root_kind == "unreadable":
        python_shim = tmp_path / "python-shim"
        python_shim.mkdir()
        (python_shim / "sitecustomize.py").write_text(
            """from pathlib import Path
import os

_original_iterdir = Path.iterdir


def _deny_artifact_root(path: Path):
    if path == Path(os.environ["INPUT_OUT_DIR"]):
        raise PermissionError("simulated unreadable artifact root")
    return _original_iterdir(path)


Path.iterdir = _deny_artifact_root
""",
            encoding="utf-8",
            newline="\n",
        )
        python_path = os.pathsep.join(part for part in [str(python_shim), python_path] if part)
    env = {
        **os.environ,
        "GITHUB_OUTPUT": "github-output.txt",
        "GITHUB_STEP_SUMMARY": "step-summary.md",
        "FAKE_ARGS_FILE": "args.bin",
        "FAKE_CREATE_RUN": str(create_run).lower(),
        "FAKE_EXIT_CODE": str(exit_code),
        "INPUT_MODE": mode,
        "INPUT_PLAN": "docs/plans/change.md",
        "INPUT_REVIEWERS": "openai:model-a,openai:model-b",
        "INPUT_API_TOKEN": "hosted-token",
        "INPUT_API_BASE_URL": "https://quorum.example.test",
        "INPUT_CONFIG": "krystal-quorum.toml",
        "INPUT_OUT_DIR": "artifacts",
        "INPUT_ROUND2": "true",
        "INPUT_REQUIRE_DIVERSITY": "true",
        "INPUT_BASE": "base-sha",
        "INPUT_HEAD": "head-sha",
        "INPUT_REPO": ".",
        "INPUT_MAX_DIFF_CHARS": "170000",
        "INPUT_MAX_REVIEW_CHARS": "230000",
        "INPUT_CONTEXT_LINES": "12",
        "INPUT_INCLUDE_UNTRACKED": "false",
        "INPUT_ALLOW_UNTRACKED_EXTERNAL": "true",
        "INPUT_ALLOW_SECRET_LOOKING_INPUT": "true",
        "PYTHONPATH": python_path,
    }
    shell = f'export PATH="$PWD/fake-bin:$PATH"\n{_run_script(ACTION_PATHS[0])}'
    completed = subprocess.run(
        [_find_bash(), "-e", "-o", "pipefail", "-c", shell],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    args = (
        [part.decode() for part in args_file.read_bytes().split(b"\0") if part]
        if args_file.exists()
        else []
    )
    outputs = github_output.read_text(encoding="utf-8") if github_output.exists() else ""
    summary = step_summary.read_text(encoding="utf-8") if step_summary.exists() else ""
    return completed, args, outputs, summary


def test_action_input_contracts_match_except_intentional_setup_defaults() -> None:
    root_inputs = _parse_mapping_section(ACTION_PATHS[0], "inputs")
    development_inputs = _parse_mapping_section(ACTION_PATHS[1], "inputs")

    assert set(root_inputs) == COMMON_INPUTS | {"python-version", "setup-python"}
    assert set(development_inputs) == COMMON_INPUTS
    assert "approval" not in root_inputs
    assert "approval" not in development_inputs
    assert root_inputs["plan"]["required"] is True
    assert development_inputs["plan"]["required"] is True
    for input_name in COMMON_INPUTS - {"plan", "package-spec"}:
        assert root_inputs[input_name] == development_inputs[input_name]
        assert root_inputs[input_name]["required"] is False
        assert root_inputs[input_name]["default"] == COMMON_DEFAULTS[input_name]

    assert root_inputs["package-spec"]["default"] == "krystal-quorum==0.7.0"
    assert development_inputs["package-spec"]["default"] == "."
    assert root_inputs["python-version"]["default"] == "3.12"
    assert root_inputs["setup-python"]["default"] == "true"


def test_action_output_contracts_are_identical() -> None:
    root_outputs = _parse_mapping_section(ACTION_PATHS[0], "outputs")
    development_outputs = _parse_mapping_section(ACTION_PATHS[1], "outputs")

    assert root_outputs == development_outputs
    assert set(root_outputs) == {"output-dir", "latest-output-dir", "summary-path"}
    assert root_outputs["output-dir"]["value"] == "${{ steps.run-quorum.outputs.output-dir }}"
    assert root_outputs["latest-output-dir"]["value"] == (
        "${{ steps.run-quorum.outputs.latest-output-dir }}"
    )
    assert root_outputs["summary-path"]["value"] == (
        "${{ steps.run-quorum.outputs.summary-path }}"
    )


def test_action_run_scripts_are_identical_and_support_review_and_diff() -> None:
    root_script = _run_script(ACTION_PATHS[0])
    development_script = _run_script(ACTION_PATHS[1])

    assert root_script == development_script
    for expected in [
        'case "$INPUT_MODE" in',
        'args=(review "$INPUT_PLAN" --reviewers "$INPUT_REVIEWERS"',
        "args=(diff --plan",
        'args+=(--head "$INPUT_HEAD")',
        "--base",
        "--repo",
        "--max-diff-chars",
        "--max-review-chars",
        "--context-lines",
        "--include-untracked",
        "--no-include-untracked",
        "--allow-untracked-external",
        "--allow-secret-looking-input",
        'cat "$summary_path" >> "$GITHUB_STEP_SUMMARY"',
        "No run-specific summary was produced",
        'exit "$code"',
    ]:
        assert expected in root_script
    assert root_script.index('echo "output-dir=$INPUT_OUT_DIR"') < root_script.index(
        'before_dirs="$(python'
    )
    assert "--approval" not in root_script


def test_diff_mode_forwards_exact_standalone_arguments(tmp_path: Path) -> None:
    completed, args, _, _ = _run_action_shell(tmp_path)

    assert completed.returncode == 0
    assert args == [
        "diff",
        "--plan",
        "docs/plans/change.md",
        "--base",
        "base-sha",
        "--head",
        "head-sha",
        "--repo",
        ".",
        "--reviewers",
        "openai:model-a,openai:model-b",
        "--out-dir",
        "artifacts",
        "--config",
        "krystal-quorum.toml",
        "--round2",
        "--require-diversity",
        "--max-diff-chars",
        "170000",
        "--max-review-chars",
        "230000",
        "--context-lines",
        "12",
        "--no-include-untracked",
        "--allow-untracked-external",
        "--allow-secret-looking-input",
    ]
    assert "--approval" not in args


def test_review_mode_preserves_existing_arguments(tmp_path: Path) -> None:
    completed, args, _, _ = _run_action_shell(tmp_path, mode="review")

    assert completed.returncode == 0
    assert args == [
        "review",
        "docs/plans/change.md",
        "--reviewers",
        "openai:model-a,openai:model-b",
        "--out-dir",
        "artifacts",
        "--api-token",
        "hosted-token",
        "--api-base-url",
        "https://quorum.example.test",
        "--config",
        "krystal-quorum.toml",
        "--round2",
        "--require-diversity",
    ]


@pytest.mark.parametrize(
    ("exit_code", "create_run"),
    [(0, True), (1, True), (2, True), (3, False)],
)
def test_shell_preserves_exit_code_and_reports_only_current_run_artifacts(
    tmp_path: Path,
    exit_code: int,
    create_run: bool,
) -> None:
    completed, _, outputs, summary = _run_action_shell(
        tmp_path,
        exit_code=exit_code,
        create_run=create_run,
    )

    assert completed.returncode == exit_code
    assert "output-dir=artifacts\n" in outputs
    if create_run:
        assert f"latest-output-dir=artifacts/run-{exit_code}\n" in outputs
        assert f"summary-path=artifacts/run-{exit_code}/summary.md\n" in outputs
        assert summary == f"# Fake summary\n\nExit code {exit_code}.\n"
    else:
        assert "latest-output-dir=" not in outputs
        assert "summary-path=" not in outputs
        assert "No run-specific summary was produced" in summary
        assert f"code `{exit_code}`" in summary
        assert "stale-run" not in summary


@pytest.mark.parametrize("artifact_root_kind", ["file", "unreadable"])
def test_discovery_failure_still_emits_root_and_preflight_summary(
    tmp_path: Path,
    artifact_root_kind: str,
) -> None:
    completed, args, outputs, summary = _run_action_shell(
        tmp_path,
        exit_code=3,
        create_run=False,
        artifact_root_kind=artifact_root_kind,
    )

    assert completed.returncode == 3
    assert args[0] == "diff"
    assert outputs == "output-dir=artifacts\n"
    assert "No run-specific summary was produced" in summary
    assert "code `3`" in summary
    assert "summary.md" not in summary
