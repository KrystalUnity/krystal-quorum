from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from krystal_quorum.approval import ApprovalReceipt, canonical_json_sha256
from krystal_quorum.models import ReconciledVerdict, ReviewIssue

UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class PersistenceError(RuntimeError):
    """A persistence failure that retains any partially created run directory."""

    def __init__(self, message: str, partial_path: Path | None = None) -> None:
        super().__init__(message)
        self.partial_path = partial_path


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


def _reviewer_filename(reviewer: str) -> str:
    safe = UNSAFE_FILENAME_CHARS.sub("_", reviewer).strip("._-") or "reviewer"
    safe = safe[:80].rstrip("._-") or "reviewer"
    if safe.upper() in WINDOWS_RESERVED_NAMES:
        safe = f"{safe}_reviewer"
    if safe != reviewer:
        digest = hashlib.sha256(reviewer.encode("utf-8")).hexdigest()[:8]
        safe = f"{safe}_{digest}"
    return f"{safe}.json"


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


def _issue_cluster_lines(result: ReconciledVerdict) -> list[str]:
    lines = ["## Issue Clusters\n\n"]
    if not result.issue_clusters:
        lines.append("- None.\n\n")
        return lines
    for cluster in result.issue_clusters:
        status = "shared" if cluster.shared else "singleton"
        reviewers = ", ".join(cluster.reviewers)
        lines.append(
            f"- **{cluster.topic}** ({status}, reviewers: {reviewers}): "
            f"{cluster.match_reason}\n"
        )
        for edge in cluster.edges:
            lines.append(
                f"  Edge: `{edge.left_reviewer}:{edge.left_issue_id}` <-> "
                f"`{edge.right_reviewer}:{edge.right_issue_id}` - {edge.match_reason}\n"
            )
        lines.append(f"  Representative: {cluster.representative.claim}\n")
    lines.append("\n")
    return lines


def build_summary(result: ReconciledVerdict) -> str:
    lines = [
        "# Krystal Quorum Review Summary\n\n",
        f"Schema: `{result.schema_version}`\n\n",
        f"Verdict: **{result.merged_verdict.value}**\n\n",
        f"Confidence: `{result.confidence:.2f}`\n\n",
        f"Reviewers: `{', '.join(result.reviewers_used)}`\n\n",
        f"Diversity: `{result.diversity.status}`\n\n",
    ]
    if result.round2_delta is not None:
        lines.append(f"Round 2 Delta: `{result.round2_delta}`\n\n")
    if result.abstained_reviewers:
        lines.append(f"Abstained: `{', '.join(result.abstained_reviewers)}`\n\n")
    lines.extend(_issue_lines("Shared Blockers", result.shared_blocking_issues))
    lines.extend(_issue_lines("Singleton Blockers", result.singleton_blocking_issues))
    lines.extend(_issue_cluster_lines(result))
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
    receipt: ApprovalReceipt | None = None,
) -> Path:
    reconciled_json = result.model_dump_json(indent=2)
    if receipt is not None:
        reconciled_payload = json.loads(reconciled_json)
        if result.merged_verdict.value != "APPROVE":
            raise PersistenceError("Approval receipt requires an APPROVE reconciliation")
        if canonical_json_sha256(reconciled_payload) != receipt.reconciled_sha256:
            raise PersistenceError("Approval receipt does not match reconciled result")

    run_dir: Path | None = None
    try:
        run_dir = _run_dir(out_dir, plan_path)
        (run_dir / "plan_input.md").write_text(plan_text, encoding="utf-8")
        (run_dir / "plan_input.sha256").write_text(
            f"{result.plan_sha256}\n", encoding="utf-8"
        )
        (run_dir / "reconciled.json").write_text(reconciled_json, encoding="utf-8")
        (run_dir / "summary.md").write_text(build_summary(result), encoding="utf-8")

        round1_dir = run_dir / "round1"
        round1_dir.mkdir()
        for output in result.round1_outputs:
            (round1_dir / _reviewer_filename(output.reviewer)).write_text(
                json.dumps(output.model_dump(mode="json"), indent=2),
                encoding="utf-8",
            )
        if result.round2_outputs:
            round2_dir = run_dir / "round2"
            round2_dir.mkdir()
            for output in result.round2_outputs:
                (round2_dir / _reviewer_filename(output.reviewer)).write_text(
                    json.dumps(output.model_dump(mode="json"), indent=2),
                    encoding="utf-8",
                )
        if receipt is not None:
            (run_dir / "approval.json").write_text(
                receipt.model_dump_json(indent=2),
                encoding="utf-8",
            )
    except OSError as exc:
        raise PersistenceError(f"Could not persist review artifacts: {exc}", run_dir) from exc
    return run_dir
