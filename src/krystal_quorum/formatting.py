from __future__ import annotations

from pathlib import Path
from textwrap import shorten
from typing import Any

from krystal_quorum.models import ReconciledVerdict


def json_output(result: ReconciledVerdict, run_dir: Path) -> dict[str, Any]:
    output: dict[str, Any] = {
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
    return output


def pretty_output(result: ReconciledVerdict, run_dir: Path, *, width: int = 78) -> str:
    lines = [
        _rule("Krystal Quorum", width),
        f"VERDICT: {result.merged_verdict.value} | Confidence: {result.confidence:.2f}",
        f"Reviewers: {', '.join(result.reviewers_used)}",
        f"Diversity: {result.diversity.status}"
        + (f" ({result.diversity.reason})" if result.diversity.reason else ""),
        "",
        _section("Shared Blockers", len(result.shared_blocking_issues)),
    ]
    lines.extend(_issue_lines(result.shared_blocking_issues, width))
    lines.append(_section("Singleton Blockers", len(result.singleton_blocking_issues)))
    lines.extend(_issue_lines(result.singleton_blocking_issues, width))

    suggestions = [
        suggestion
        for output in (result.round2_outputs or result.round1_outputs)
        for suggestion in output.suggestions
    ]
    lines.append(_section("Suggestions", len(suggestions)))
    if suggestions:
        for suggestion in suggestions:
            lines.append(
                "- "
                + shorten(
                    f"[{suggestion.section}] {suggestion.claim}",
                    width=max(20, width - 2),
                    placeholder="...",
                )
            )
    else:
        lines.append("- none")

    lines.append(_section("Human Triage", len(result.unresolved_for_human)))
    if result.unresolved_for_human:
        for item in result.unresolved_for_human:
            lines.append("- " + shorten(item, width=max(20, width - 2), placeholder="..."))
    else:
        lines.append("- none")

    if result.abstained_reviewers:
        lines.append(f"Abstained: {', '.join(result.abstained_reviewers)}")
    if result.round2_delta is not None:
        lines.append(f"Round 2 changed verdicts: {result.round2_delta}")

    lines.extend(["", f"Artifacts: {run_dir}", _rule("", width)])
    return "\n".join(lines)


def _rule(title: str, width: int) -> str:
    if not title:
        return "+" + "-" * (width - 2) + "+"
    label = f" {title} "
    remaining = max(0, width - 2 - len(label))
    return "+" + label + "-" * remaining + "+"


def _section(label: str, count: int) -> str:
    return f"{label} ({count})"


def _issue_lines(issues: list[Any], width: int) -> list[str]:
    if not issues:
        return ["- none"]
    return [
        "- "
        + shorten(
            f"[{issue.section}] {issue.claim}",
            width=max(20, width - 2),
            placeholder="...",
        )
        for issue in issues
    ]
