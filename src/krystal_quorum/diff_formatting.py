from __future__ import annotations

from typing import Any

from krystal_quorum.diff_models import DiffResult
from krystal_quorum.diff_service import DryRunMetadata


def diff_json_output(result: DiffResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def dry_run_json_output(metadata: DryRunMetadata) -> dict[str, Any]:
    return {
        "review_kind": "diff",
        "dry_run": True,
        "plan_sha256": metadata.plan_sha256,
        "approval_sha256": metadata.approval_sha256,
        "diff_sha256": metadata.diff_sha256,
        "review_input_sha256": metadata.review_input_sha256,
        "plan_chars": metadata.plan_chars,
        "diff_chars": metadata.diff_chars,
        "review_input_chars": metadata.review_input_chars,
        "review_input_rough_tokens": metadata.review_input_rough_tokens,
        "commitment_count": metadata.commitment_count,
        "changed_file_count": metadata.changed_file_count,
        "destinations": list(metadata.destinations),
        "external_destinations": list(metadata.external_destinations),
        "warning_classes": list(metadata.warning_classes),
        "warning_counts": dict(metadata.warning_counts),
    }


def dry_run_pretty_output(metadata: DryRunMetadata) -> str:
    external = ", ".join(metadata.external_destinations) or "none"
    warnings = ", ".join(metadata.warning_classes) or "none"
    return "\n".join(
        [
            "Diff preflight: dry run",
            f"Plan SHA256: {metadata.plan_sha256}",
            f"Approval SHA256: {metadata.approval_sha256 or 'none'}",
            f"Diff SHA256: {metadata.diff_sha256}",
            f"Review input SHA256: {metadata.review_input_sha256}",
            f"Characters: plan={metadata.plan_chars}, diff={metadata.diff_chars}, "
            f"review_input={metadata.review_input_chars}",
            f"Rough review-input tokens: {metadata.review_input_rough_tokens}",
            f"Commitments: {metadata.commitment_count}",
            f"Changed files: {metadata.changed_file_count}",
            f"Reviewer destinations: {', '.join(metadata.destinations)}",
            f"External destinations: {external}",
            f"Warning classes: {warnings}",
        ]
    )


def _evidence_text(evidence: list[str]) -> str:
    if not evidence:
        return "not present in diff"
    visible = evidence[:3]
    if len(evidence) > 3:
        visible.append(f"and {len(evidence) - 3} more")
    return "; ".join(visible)


def diff_pretty_output(result: DiffResult) -> str:
    lines = [
        f"Verdict: {result.verdict.value}",
        f"Plan provenance: {result.plan_provenance.value.replace('_', ' ')}",
        f"Quorum health: {result.quorum.health.value}",
        f"Usable reviewers: {result.quorum.usable_reviewers}/{result.quorum.total_reviewers}",
        f"Distinct families: {result.quorum.distinct_families}",
        f"Agreement ratio: {result.quorum.agreement_ratio:.2f}",
        f"Contradictions: {result.quorum.contradiction_count}",
        "",
        "Commitment Coverage",
        "ID | Status | Corroborated | Evidence",
    ]
    if result.coverage:
        for item in result.coverage:
            lines.append(
                f"{item.commitment_id} | {item.status.value} | "
                f"{'yes' if item.corroborated else 'no'} | {_evidence_text(item.evidence)}"
            )
    else:
        lines.append("None")

    lines.extend(["", "Unplanned Scope Findings"])
    if result.scope_findings:
        for finding in result.scope_findings:
            evidence = finding.evidence or "not present in diff"
            lines.append(
                f"{finding.risk.value}/{finding.category.value}: {finding.claim} [{evidence}]"
            )
    else:
        lines.append("None")

    lines.extend(["", "Human Triage"])
    lines.extend(result.unresolved_for_human or ["None"])
    lines.extend(["", f"Artifacts: {result.output_dir}"])
    return "\n".join(lines)
