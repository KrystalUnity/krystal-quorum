from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from typer.testing import CliRunner

import krystal_quorum.cli as cli_module
from krystal_quorum.cli import app
from krystal_quorum.diff_models import DIFF_CLAUSE_IDS, DiffReviewerOutput
from krystal_quorum.diff_service import execute_diff_run as real_execute_diff_run
from krystal_quorum.models import ClauseStatus, Verdict


PLAN_TEXT = "## Acceptance Criteria\n- [AC-1] Ship the implementation.\n"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repo(tmp_path: Path, *, dirty: bool = True) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Tests")
    _git(repo, "config", "core.autocrlf", "false")
    plan = repo / "plan.md"
    app_file = repo / "app.py"
    plan.write_text(PLAN_TEXT, encoding="utf-8")
    app_file.write_text("implemented = False\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".krystal-quorum/\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    base_sha = _git(repo, "rev-parse", "HEAD")
    if dirty:
        app_file.write_text("implemented = True\n", encoding="utf-8")
    return repo, plan, app_file, base_sha


def _diff_args(
    repo: Path,
    plan: Path,
    out_dir: Path,
    *,
    base: str | None = "HEAD",
) -> list[str]:
    args = [
        "diff",
        "--plan",
        str(plan),
        "--repo",
        str(repo),
        "--reviewers",
        "mock",
        "--out-dir",
        str(out_dir),
    ]
    if base is not None:
        args.extend(["--base", base])
    return args


def test_diff_help_exposes_the_approved_command_surface() -> None:
    root_help = CliRunner().invoke(app, ["--help"], terminal_width=160)
    diff_help = CliRunner().invoke(app, ["diff", "--help"], terminal_width=160)

    assert root_help.exit_code == 0
    assert "diff" in root_help.output
    assert diff_help.exit_code == 0
    for option in (
        "--plan",
        "--approval",
        "--base",
        "--head",
        "--repo",
        "--reviewers",
        "--config",
        "--out-dir",
        "--round2",
        "--require-diversity",
        "--max-plan-chars",
        "--max-diff-chars",
        "--max-review-chars",
        "--context-lines",
        "--include-untracked",
        "--no-include-untracked",
        "--allow-secret-looking-input",
        "--allow-untracked-external",
        "--dry-run",
        "--format",
    ):
        assert option in diff_help.output


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--approval", "missing.json", "--base", "HEAD"], "approval and base"),
        ([], "requires base"),
    ],
)
def test_diff_rejects_invalid_verified_and_standalone_combinations(
    tmp_path: Path,
    extra: list[str],
    message: str,
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN_TEXT, encoding="utf-8")

    result = CliRunner().invoke(app, ["diff", "--plan", str(plan), *extra])

    assert result.exit_code == 3
    assert result.stderr.startswith("krystal-quorum error:")
    assert message in result.stderr


def test_diff_rejects_invalid_format_inside_command_with_stable_error(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN_TEXT, encoding="utf-8")
    out_dir = tmp_path / "runs"

    result = CliRunner().invoke(
        app,
        [
            "diff",
            "--plan",
            str(plan),
            "--base",
            "HEAD",
            "--out-dir",
            str(out_dir),
            "--format",
            "yaml",
        ],
    )

    assert result.exit_code == 3
    assert result.stderr.startswith("krystal-quorum error:")
    assert "--format must be one of: json, pretty" in result.stderr
    assert "Invalid value for '--format'" not in result.stderr
    assert not out_dir.exists()


def test_diff_dry_run_is_redacted_and_never_executes_or_persists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, plan, _, base_sha = _repo(tmp_path)
    out_dir = tmp_path / "dry-runs"

    def explode(*args, **kwargs):
        raise AssertionError("dry-run must not execute reviewers")

    monkeypatch.setattr(cli_module, "execute_diff_run", explode, raising=False)

    result = CliRunner().invoke(
        app,
        [*_diff_args(repo, plan, out_dir, base=base_sha), "--dry-run", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["review_kind"] == "diff"
    assert payload["dry_run"] is True
    assert payload["destinations"] == ["mock"]
    assert payload["changed_file_count"] == 1
    assert "plan_sha256" in payload
    assert PLAN_TEXT.strip() not in result.output
    assert "implemented = True" not in result.output
    assert not out_dir.exists()


def test_standalone_working_tree_json_has_run_specific_provenance(
    tmp_path: Path,
) -> None:
    repo, plan, _, base_sha = _repo(tmp_path)
    out_dir = tmp_path / "runs"

    result = CliRunner().invoke(
        app,
        [*_diff_args(repo, plan, out_dir, base=base_sha), "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "krystal-quorum.diff.v1"
    assert payload["verdict"] == "REVISE"
    assert payload["plan_provenance"] == "unverified_reference"
    assert payload["git"]["base_sha"] == base_sha
    assert payload["git"]["working_tree"] is True
    assert Path(payload["output_dir"]).is_dir()
    assert payload["output_dir"] != str(out_dir)


def test_diff_pretty_output_leads_with_verdict_provenance_quorum_and_matrix(
    tmp_path: Path,
) -> None:
    repo, plan, _, base_sha = _repo(tmp_path)

    result = CliRunner().invoke(
        app,
        [*_diff_args(repo, plan, tmp_path / "pretty", base=base_sha), "--format", "pretty"],
    )

    assert result.exit_code == 1
    required = (
        "Verdict: REVISE",
        "Plan provenance: unverified reference",
        "Quorum health:",
        "Commitment Coverage",
        "AC-1",
        "NOT_EVIDENT",
        "not present in diff",
        "Artifacts:",
    )
    positions = [result.stdout.index(value) for value in required]
    assert positions == sorted(positions)


def test_committed_head_uses_resolved_head_and_merge_base(tmp_path: Path) -> None:
    repo, plan, _, base_sha = _repo(tmp_path)
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "implementation")
    head_sha = _git(repo, "rev-parse", "HEAD")

    result = CliRunner().invoke(
        app,
        [
            *_diff_args(repo, plan, tmp_path / "committed", base=base_sha),
            "--head",
            head_sha,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["git"]["working_tree"] is False
    assert payload["git"]["head_ref"] == head_sha
    assert payload["git"]["head_sha"] == head_sha
    assert payload["git"]["merge_base_sha"] == base_sha


def test_verified_mode_uses_exact_receipt_baseline_and_rejects_base_override(
    tmp_path: Path,
) -> None:
    repo, plan, app_file, base_sha = _repo(tmp_path, dirty=False)
    review_out = repo / ".krystal-quorum" / "reviews"
    review = CliRunner().invoke(
        app,
        [
            "review",
            str(plan),
            "--bind-repo",
            str(repo),
            "--out-dir",
            str(review_out),
            "--format",
            "json",
        ],
    )
    assert review.exit_code == 0, review.output
    approval = Path(json.loads(review.stdout)["approval_path"])
    app_file.write_text("implemented = True\n", encoding="utf-8")

    verified = CliRunner().invoke(
        app,
        [
            *_diff_args(repo, plan, tmp_path / "verified", base=None),
            "--approval",
            str(approval),
            "--format",
            "json",
        ],
    )
    override = CliRunner().invoke(
        app,
        [
            *_diff_args(repo, plan, tmp_path / "override", base=base_sha),
            "--approval",
            str(approval),
        ],
    )

    assert verified.exit_code == 1
    payload = json.loads(verified.stdout)
    assert payload["plan_provenance"] == "verified_receipt"
    assert payload["git"]["base_sha"] == base_sha
    assert payload["plan"]["approval_sha256"] is not None
    assert override.exit_code == 3
    assert "approval and base" in override.stderr


def test_hosted_diff_is_rejected_before_http_or_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, plan, _, base_sha = _repo(tmp_path)
    out_dir = tmp_path / "hosted"

    def explode(*args, **kwargs):
        raise AssertionError("hosted diff must fail before HTTP or execution")

    monkeypatch.setattr("krystal_quorum.hosted.httpx.Client", explode)
    monkeypatch.setattr(cli_module, "execute_diff_run", explode, raising=False)
    args = _diff_args(repo, plan, out_dir, base=base_sha)
    args[args.index("mock")] = "hosted:test"

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 3
    assert result.stderr.startswith("krystal-quorum error:")
    assert "hosted diff review is unsupported" in result.stderr
    assert not out_dir.exists()


def test_post_start_reconciliation_failure_persists_auditable_run_and_exits_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, plan, _, base_sha = _repo(tmp_path)
    out_dir = tmp_path / "failed-reconciliation"

    class IncompleteReviewer:
        id = "mock"

        async def review_diff_round1(self, *args, **kwargs):
            return DiffReviewerOutput(
                reviewer=self.id,
                round=1,
                verdict=Verdict.REVISE,
                confidence=0.5,
                commitment_coverage=[],
                scope_findings=[],
                blocking_issues=[],
                suggestions=[],
                per_clause={clause: ClauseStatus.UNCLEAR for clause in DIFF_CLAUSE_IDS},
                raw_response="valid output with incomplete commitment coverage",
                elapsed_seconds=0.01,
            )

    monkeypatch.setattr(
        "krystal_quorum.diff_service.build_reviewers_from_specs",
        lambda specs: [IncompleteReviewer()],
    )

    result = CliRunner().invoke(
        app,
        [*_diff_args(repo, plan, out_dir, base=base_sha), "--format", "json"],
    )

    assert result.exit_code == 3
    run_dirs = list(out_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    reconciled = json.loads((run_dir / "reconciled.json").read_text(encoding="utf-8"))
    assert reconciled["verdict"] == "ABSTAIN"
    assert reconciled["coverage"] == []
    assert reconciled["unresolved_for_human"] == [
        "Diff reconciliation failed after reviewer execution began (ValueError); "
        "reviewer outputs were preserved for audit."
    ]
    reviewer_output = json.loads(
        (run_dir / "round1" / "mock.json").read_text(encoding="utf-8")
    )
    assert reviewer_output["commitment_coverage"] == []
    assert (run_dir / "manifest.json").is_file()


@pytest.mark.parametrize(("verdict", "exit_code"), [(Verdict.APPROVE, 0), (Verdict.BLOCK, 2)])
def test_diff_maps_approve_and_block_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verdict: Verdict,
    exit_code: int,
) -> None:
    repo, plan, _, base_sha = _repo(tmp_path)

    async def force_verdict(prepared):
        executed = await real_execute_diff_run(prepared)
        return replace(
            executed,
            result=executed.result.model_copy(update={"verdict": verdict}),
        )

    monkeypatch.setattr(cli_module, "execute_diff_run", force_verdict, raising=False)

    result = CliRunner().invoke(
        app,
        [*_diff_args(repo, plan, tmp_path / verdict.value, base=base_sha), "--format", "json"],
    )

    assert result.exit_code == exit_code
    assert json.loads(result.stdout)["verdict"] == verdict.value


def test_module_entry_exposes_diff_help() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root / "src"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    completed = subprocess.run(
        [sys.executable, "-m", "krystal_quorum", "diff", "--help"],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--approval" in completed.stdout
    assert "--dry-run" in completed.stdout
