from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from krystal_quorum.config import build_reviewers
from krystal_quorum.diversity import analyze_reviewer_objects
from krystal_quorum.init_command import InitError, install_integration_templates
from krystal_quorum.models import DiversityReport, ReconciledVerdict, Verdict
from krystal_quorum.persist import persist_run
from krystal_quorum.reconcile import reconcile
from krystal_quorum.reviewers.base import ReviewerProtocol

app = typer.Typer(help="Preflight review for AI coding plans.")
DEFAULT_MAX_PLAN_CHARS = 120_000


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
    output = {
        "schema_version": result.schema_version,
        "verdict": result.merged_verdict.value,
        "confidence": result.confidence,
        "reviewers_used": result.reviewers_used,
        "diversity": result.diversity.status,
        "diversity_reason": result.diversity.reason,
        "diversity_reviewers": [
            reviewer.model_dump(mode="json") for reviewer in result.diversity.reviewers
        ],
        "abstained_reviewers": result.abstained_reviewers,
        "unresolved_for_human": result.unresolved_for_human,
        "output_dir": str(run_dir),
    }
    if result.round2_delta is not None:
        output["round2_delta"] = result.round2_delta
        output["round2_comparisons"] = [
            comparison.model_dump(mode="json") for comparison in result.round2_comparisons
        ]
    typer.echo(json.dumps(output, indent=2))
    raise typer.Exit(_exit_code(result.merged_verdict))


@app.command()
def init(
    target: str = typer.Option(
        ...,
        "--target",
        help="Integration target: claude-code, hermes, or openclaw.",
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
) -> None:
    """Install project-local agent integration templates."""
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
