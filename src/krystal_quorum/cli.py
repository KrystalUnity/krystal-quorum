from __future__ import annotations

import asyncio
import json
import os
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Literal

import typer

from krystal_quorum.approval import (
    ApprovalError,
    BoundRepositoryState,
    build_approval_receipt,
    prepare_bound_review,
    revalidate_bound_review,
)
from krystal_quorum.commitments import CommitmentError
from krystal_quorum.config import build_reviewers
from krystal_quorum.diff_formatting import (
    diff_json_output,
    diff_pretty_output,
    dry_run_json_output,
    dry_run_pretty_output,
)
from krystal_quorum.diff_persist import persist_diff_run
from krystal_quorum.diff_service import (
    DEFAULT_MAX_PLAN_CHARS as DEFAULT_DIFF_MAX_PLAN_CHARS,
    DEFAULT_MAX_REVIEW_CHARS,
    DiffRunOptions,
    DiffServiceError,
    execute_diff_run,
    prepare_diff_run,
)
from krystal_quorum.diffing import (
    DEFAULT_CONTEXT_LINES,
    DEFAULT_MAX_DIFF_CHARS,
    DiffCaptureError,
)
from krystal_quorum.diversity import analyze_reviewer_objects
from krystal_quorum.formatting import json_output, pretty_output
from krystal_quorum.hosted import (
    HostedReviewError,
    hosted_json_output,
    hosted_pack_from_reviewers,
    hosted_pretty_output,
    run_hosted_review,
)
from krystal_quorum.init_command import InitError, available_targets, install_integration_templates
from krystal_quorum.models import DiversityReport, ReconciledVerdict, Verdict
from krystal_quorum.persist import PersistenceError, persist_run
from krystal_quorum.reconcile import reconcile
from krystal_quorum.reviewers.base import ReviewerProtocol

app = typer.Typer(help="Preflight review for AI coding plans.", rich_markup_mode=None)
DEFAULT_MAX_PLAN_CHARS = 120_000
DEMO_PLANS = {
    "bad": "bad-plan.md",
    "good": "good-plan.md",
}


@app.callback()
def root() -> None:
    """Preflight review for AI coding plans."""


def _exit_code(verdict: Verdict) -> int:
    if verdict == Verdict.APPROVE:
        return 0
    if verdict == Verdict.REVISE:
        return 1
    if verdict == Verdict.BLOCK:
        return 2
    return 3


def _exit_code_for_value(verdict: str) -> int:
    try:
        return _exit_code(Verdict(str(verdict).upper()))
    except ValueError:
        return 3


def _rough_token_estimate(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _plan_size_error(plan_text: str, max_plan_chars: int) -> str | None:
    if max_plan_chars <= 0 or len(plan_text) <= max_plan_chars:
        return None
    return (
        f"Plan too large: {len(plan_text)} characters "
        f"(roughly {_rough_token_estimate(plan_text)} tokens) exceeds "
        f"--max-plan-chars {max_plan_chars}. Split the plan or raise the limit."
    )


def _demo_plan_text(plan_name: Literal["bad", "good"]) -> tuple[Path, str]:
    file_name = DEMO_PLANS[plan_name]
    resource = files("krystal_quorum").joinpath("examples", file_name)
    return Path(file_name), resource.read_text(encoding="utf-8")


def _diff_failure(message: str) -> None:
    typer.echo(f"krystal-quorum error: {message}", err=True)
    raise typer.Exit(3)


def _warn_if_artifacts_not_ignored(repo_root: Path, run_dir: Path) -> None:
    try:
        relative = run_dir.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return
    if not relative.parts or relative.parts[0] != ".krystal-quorum":
        return
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "-q", "--", ".krystal-quorum/"],
            check=False,
            capture_output=True,
            shell=False,
        )
    except OSError:
        return
    if completed.returncode == 1:
        typer.echo(
            "krystal-quorum warning: diff artifacts may contain sensitive input; "
            "add `.krystal-quorum/` to the repository .gitignore",
            err=True,
        )


async def _run_review(
    plan_path: Path,
    reviewers: list[ReviewerProtocol],
    run_round2: bool,
    plan_text: str | None = None,
    diversity: DiversityReport | None = None,
) -> ReconciledVerdict:
    plan_text = plan_text if plan_text is not None else plan_path.read_text(encoding="utf-8")
    round1_outputs = await asyncio.gather(
        *(reviewer.review_round1(plan_text, timeout_s=120) for reviewer in reviewers)
    )
    round2_outputs = []
    if run_round2:
        round2_outputs = list(
            await asyncio.gather(
                *(
                    reviewer.review_round2(plan_text, list(round1_outputs), timeout_s=180)
                    for reviewer in reviewers
                )
            )
        )
    return reconcile(
        plan_path=str(plan_path),
        plan_text=plan_text,
        reviewers_used=[reviewer.id for reviewer in reviewers],
        round1_outputs=list(round1_outputs),
        round2_outputs=round2_outputs,
        diversity=diversity,
    )


@app.command()
def review(
    plan: Path,
    reviewers: str = typer.Option("mock", help="Comma-separated reviewer list."),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Optional krystal-quorum TOML config for command reviewers.",
    ),
    out_dir: Path = typer.Option(
        Path(".krystal-quorum/reviews"),
        help="Directory where review runs are written.",
    ),
    bind_repo: Path | None = typer.Option(
        None,
        "--bind-repo",
        help="Bind an approved review to the current repository HEAD.",
    ),
    round2: bool = typer.Option(False, help="Run a second cross-audit round."),
    require_diversity: bool = typer.Option(
        False,
        "--require-diversity",
        help="Exit with a configuration error when reviewer model families are not distinct.",
    ),
    max_plan_chars: int = typer.Option(
        DEFAULT_MAX_PLAN_CHARS,
        "--max-plan-chars",
        help="Maximum plan size in characters before review. Use 0 to disable.",
    ),
    output_format: Literal["json", "pretty"] = typer.Option(
        "json",
        "--format",
        help="Output format for stdout: json or pretty.",
    ),
    api_token: str | None = typer.Option(
        None,
        "--api-token",
        help="Quorum hosted API token. Falls back to KU_TOKEN.",
    ),
    api_base_url: str | None = typer.Option(
        None,
        "--api-base-url",
        help="Hosted Quorum API base URL. Defaults to KRYSTAL_QUORUM_API_BASE or https://krystalunity.com.",
    ),
) -> None:
    """Review a markdown coding plan."""
    if not plan.exists():
        typer.echo(f"Plan not found: {plan}", err=True)
        raise typer.Exit(3)

    plan_text = plan.read_text(encoding="utf-8")
    size_error = _plan_size_error(plan_text, max_plan_chars)
    if size_error:
        typer.echo(size_error, err=True)
        raise typer.Exit(3)

    bound_state: BoundRepositoryState | None = None
    if bind_repo is not None:
        try:
            bound_state = prepare_bound_review(
                bind_repo,
                plan,
                out_dir,
                plan_text=plan_text,
            )
        except ApprovalError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(3) from exc

    try:
        hosted_pack = hosted_pack_from_reviewers(reviewers)
    except HostedReviewError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(3) from exc
    if hosted_pack:
        if bound_state is not None:
            typer.echo("--bind-repo is not available for hosted reviewers", err=True)
            raise typer.Exit(3)
        resolved_token = (api_token or os.getenv("KU_TOKEN") or "").strip()
        if not resolved_token:
            typer.echo("--api-token or KU_TOKEN is required for hosted reviewers", err=True)
            raise typer.Exit(3)
        try:
            response, run_dir = run_hosted_review(
                plan_path=plan,
                plan_text=plan_text,
                pack_key=hosted_pack,
                out_dir=out_dir,
                api_token=resolved_token,
                api_base_url=api_base_url,
            )
        except HostedReviewError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(3) from exc
        output = hosted_json_output(response, run_dir)
        if output_format == "pretty":
            typer.echo(hosted_pretty_output(response, run_dir))
        else:
            typer.echo(json.dumps(output, indent=2))
        raise typer.Exit(_exit_code_for_value(str(output.get("verdict") or "ABSTAIN")))

    try:
        reviewer_instances = build_reviewers(reviewers, config_path=config)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(3) from exc

    diversity = analyze_reviewer_objects(reviewer_instances)
    if require_diversity and diversity.status == "low":
        typer.echo(f"reviewer diversity is low: {diversity.reason}", err=True)
        raise typer.Exit(3)

    result = asyncio.run(
        _run_review(
            plan,
            reviewer_instances,
            round2,
            plan_text=plan_text,
            diversity=diversity,
        )
    )
    receipt = None
    bound_error: ApprovalError | None = None
    if bound_state is not None:
        try:
            revalidate_bound_review(bound_state)
            if result.merged_verdict == Verdict.APPROVE:
                receipt = build_approval_receipt(bound_state, result)
        except ApprovalError as exc:
            bound_error = exc

    try:
        if receipt is None:
            run_dir = persist_run(out_dir, plan, plan_text, result)
        else:
            run_dir = persist_run(out_dir, plan, plan_text, result, receipt=receipt)
    except PersistenceError as exc:
        typer.echo(str(exc), err=True)
        if exc.partial_path is not None:
            typer.echo(f"Partial artifacts: {exc.partial_path}", err=True)
        raise typer.Exit(3) from exc
    approval_path = run_dir / "approval.json" if receipt is not None else None
    if output_format == "pretty":
        typer.echo(pretty_output(result, run_dir, approval_path=approval_path))
    else:
        typer.echo(
            json.dumps(json_output(result, run_dir, approval_path=approval_path), indent=2)
        )
    if bound_error is not None:
        typer.echo(str(bound_error), err=True)
        raise typer.Exit(3)
    raise typer.Exit(_exit_code(result.merged_verdict))


@app.command("diff")
def diff_command(
    plan: Path = typer.Option(..., "--plan", help="Plan whose commitments are reviewed."),
    approval: Path | None = typer.Option(
        None,
        "--approval",
        help="Approval receipt from a repository-bound plan review.",
    ),
    base: str | None = typer.Option(
        None,
        "--base",
        help="Standalone baseline ref. Cannot be combined with --approval.",
    ),
    head: str | None = typer.Option(
        None,
        "--head",
        help="Optional committed head ref; omit to review the working tree.",
    ),
    repo: Path = typer.Option(Path("."), "--repo", help="Git repository to inspect."),
    reviewers: str = typer.Option("mock", help="Comma-separated reviewer list."),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Optional krystal-quorum TOML reviewer config.",
    ),
    out_dir: Path = typer.Option(
        Path(".krystal-quorum/reviews"),
        "--out-dir",
        help="Artifact root for completed diff runs.",
    ),
    round2: bool = typer.Option(False, "--round2", help="Run cross-audit round 2."),
    require_diversity: bool = typer.Option(
        False,
        "--require-diversity",
        help="Require distinct reviewer model families.",
    ),
    max_plan_chars: int = typer.Option(
        DEFAULT_DIFF_MAX_PLAN_CHARS,
        "--max-plan-chars",
        help="Maximum plan characters; 0 disables only this bound.",
    ),
    max_diff_chars: int = typer.Option(
        DEFAULT_MAX_DIFF_CHARS,
        "--max-diff-chars",
        help="Maximum canonical diff characters.",
    ),
    max_review_chars: int = typer.Option(
        DEFAULT_MAX_REVIEW_CHARS,
        "--max-review-chars",
        help="Maximum complete reviewer-input characters.",
    ),
    context_lines: int = typer.Option(
        DEFAULT_CONTEXT_LINES,
        "--context-lines",
        help="Unified diff context lines, from 0 to 200.",
    ),
    include_untracked: bool = typer.Option(
        True,
        "--include-untracked/--no-include-untracked",
        help="Include eligible untracked files in working-tree review.",
    ),
    allow_secret_looking_input: bool = typer.Option(
        False,
        "--allow-secret-looking-input",
        help="Allow warning-class input to external reviewers.",
    ),
    allow_untracked_external: bool = typer.Option(
        False,
        "--allow-untracked-external",
        help="Allow captured untracked content to external reviewers.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run bounded preflight without reviewer construction or artifacts.",
    ),
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Output format for stdout: json or pretty.",
    ),
) -> None:
    """Review implementation evidence against plan commitments."""
    if output_format not in {"json", "pretty"}:
        _diff_failure("--format must be one of: json, pretty")
    options = DiffRunOptions(
        plan=plan,
        repo=repo,
        approval=approval,
        base=base,
        head=head,
        reviewers=reviewers,
        config=config,
        out_dir=out_dir,
        round2=round2,
        require_diversity=require_diversity,
        max_plan_chars=max_plan_chars,
        max_diff_chars=max_diff_chars,
        max_review_chars=max_review_chars,
        context_lines=context_lines,
        include_untracked=include_untracked,
        allow_secret_looking_input=allow_secret_looking_input,
        allow_untracked_external=allow_untracked_external,
        dry_run=dry_run,
    )
    try:
        prepared = prepare_diff_run(options)
    except (ApprovalError, CommitmentError, DiffCaptureError, DiffServiceError, ValueError) as exc:
        _diff_failure(str(exc))

    if dry_run:
        if output_format == "pretty":
            typer.echo(dry_run_pretty_output(prepared.dry_run_metadata))
        else:
            typer.echo(json.dumps(dry_run_json_output(prepared.dry_run_metadata), indent=2))
        return

    try:
        executed = asyncio.run(execute_diff_run(prepared))
    except (DiffServiceError, OSError, RuntimeError, ValueError) as exc:
        _diff_failure(f"diff review execution failed ({type(exc).__name__})")

    try:
        run_dir, result = persist_diff_run(executed)
    except PersistenceError as exc:
        typer.echo(f"krystal-quorum error: {exc}", err=True)
        if exc.partial_path is not None:
            typer.echo(f"Partial artifacts: {exc.partial_path}", err=True)
        raise typer.Exit(3) from exc

    _warn_if_artifacts_not_ignored(prepared.snapshot.repo_root, run_dir)
    if output_format == "pretty":
        typer.echo(diff_pretty_output(result))
    else:
        typer.echo(json.dumps(diff_json_output(result), indent=2))
    raise typer.Exit(_exit_code(result.verdict))


@app.command()
def demo(
    plan: Literal["bad", "good"] = typer.Option(
        "bad",
        "--plan",
        help="Bundled demo plan to review: bad or good.",
    ),
    out_dir: Path = typer.Option(
        Path(".krystal-quorum/reviews"),
        help="Directory where demo review runs are written.",
    ),
    output_format: Literal["json", "pretty"] = typer.Option(
        "pretty",
        "--format",
        help="Output format for stdout: json or pretty.",
    ),
) -> None:
    """Run a no-key review against a bundled demo plan."""
    plan_path, plan_text = _demo_plan_text(plan)
    reviewer_instances = build_reviewers("mock", config_path=None)
    diversity = analyze_reviewer_objects(reviewer_instances)
    result = asyncio.run(
        _run_review(
            plan_path,
            reviewer_instances,
            run_round2=False,
            plan_text=plan_text,
            diversity=diversity,
        )
    )
    run_dir = persist_run(out_dir, plan_path, plan_text, result)
    if output_format == "pretty":
        typer.echo(pretty_output(result, run_dir))
    else:
        typer.echo(json.dumps(json_output(result, run_dir), indent=2))

    expected = Verdict.REVISE if plan == "bad" else Verdict.APPROVE
    if result.merged_verdict != expected:
        raise typer.Exit(_exit_code(result.merged_verdict))


@app.command()
def init(
    target: str | None = typer.Option(
        None,
        "--target",
        help="Integration target: claude-code, codex, copilot, hermes, claw, openclaw, opencode, or all.",
    ),
    path: Path = typer.Option(
        Path("."),
        "--path",
        help="Project directory where integration files should be installed.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing generated integration files.",
    ),
    list_targets: bool = typer.Option(
        False,
        "--list-targets",
        help="List supported integration targets and exit.",
    ),
) -> None:
    """Install project-local agent integration templates."""
    if list_targets:
        typer.echo("Supported init targets:")
        for item in available_targets(include_all=True):
            typer.echo(f"- {item}")
        return
    if target is None:
        typer.echo("Missing option '--target'. Use --list-targets to see choices.", err=True)
        raise typer.Exit(3)
    try:
        installed = install_integration_templates(target, path, force=force)
    except InitError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(3) from exc

    typer.echo(f"Installed {target} integration templates:")
    for installed_file in installed:
        typer.echo(f"- {installed_file}")


def main() -> None:
    app()
