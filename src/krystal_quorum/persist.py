from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from krystal_quorum.models import ReconciledVerdict, ReviewIssue


def plan_sha256(plan_text: str) -> str:
    return hashlib.sha256(plan_text.encode("utf-8")).hexdigest()


def _run_dir(out_dir: Path, plan_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stem = plan_path.stem or "plan"
    candidate = out_dir / f"{stem}_{stamp}"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = out_dir / f"{stem}_{stamp}_{suffix}"
    candidate.mkdir(parents=True)
    return candidate


def _issue_lines(title: str, issues: list[ReviewIssue]) -> list[str]:
    lines = [f"## {title}\n\n"]
    if not issues:
        lines.append("- None.\n\n")
        return lines
    for issue in issues:
        lines.append(f"- **{issue.id}** ({issue.section}): {issue.claim}\n")
        if issue.evidence:
            lines.append(f"  Evidence: {issue.evidence}\n")
    lines.append("\n")
    return lines


def build_summary(result: ReconciledVerdict) -> str:
    lines = [
        "# Krystal Quorum Review Summary\n\n",
        f"Verdict: **{result.merged_verdict.value}**\n\n",
        f"Confidence: `{result.confidence:.2f}`\n\n",
        f"Reviewers: `{', '.join(result.reviewers_used)}`\n\n",
    ]
    if result.abstained_reviewers:
        lines.append(f"Abstained: `{', '.join(result.abstained_reviewers)}`\n\n")
    lines.extend(_issue_lines("Shared Blockers", result.shared_blocking_issues))
    lines.extend(_issue_lines("Singleton Blockers", result.singleton_blocking_issues))
    lines.append("## Human Triage\n\n")
    if result.unresolved_for_human:
        for item in result.unresolved_for_human:
            lines.append(f"- {item}\n")
    else:
        lines.append("- No unresolved items.\n")
    return "".join(lines)


def persist_run(
    out_dir: Path,
    plan_path: Path,
    plan_text: str,
    result: ReconciledVerdict,
) -> Path:
    run_dir = _run_dir(out_dir, plan_path)
    (run_dir / "plan_input.md").write_text(plan_text, encoding="utf-8")
    (run_dir / "plan_input.sha256").write_text(f"{result.plan_sha256}\n", encoding="utf-8")
    (run_dir / "reconciled.json").write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (run_dir / "summary.md").write_text(build_summary(result), encoding="utf-8")

    round1_dir = run_dir / "round1"
    round1_dir.mkdir()
    for output in result.round1_outputs:
        (round1_dir / f"{output.reviewer}.json").write_text(
            json.dumps(output.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
    if result.round2_outputs:
        round2_dir = run_dir / "round2"
        round2_dir.mkdir()
        for output in result.round2_outputs:
            (round2_dir / f"{output.reviewer}.json").write_text(
                json.dumps(output.model_dump(mode="json"), indent=2),
                encoding="utf-8",
            )
    return run_dir
