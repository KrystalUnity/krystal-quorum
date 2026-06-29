from __future__ import annotations

import asyncio
import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Literal

import typer

from krystal_quorum.config import build_reviewers
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
from krystal_quorum.persist import persist_run
from krystal_quorum.reconcile import reconcile
from krystal_quorum.reviewers.base import ReviewerProtocol

app = typer.Typer(help="Preflight review for AI coding plans.")
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

    try:
        hosted_pack = hosted_pack_from_reviewers(reviewers)
    except HostedReviewError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(3) from exc
    if hosted_pack:
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
    run_dir = persist_run(out_dir, plan, plan_text, result)
    if output_format == "pretty":
        typer.echo(pretty_output(result, run_dir))
    else:
        typer.echo(json.dumps(json_output(result, run_dir), indent=2))
    raise typer.Exit(_exit_code(result.merged_verdict))


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
        help="Integration target: claude-code, codex, hermes, claw, openclaw, opencode, or all.",
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
