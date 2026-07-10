from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import TYPE_CHECKING

from krystal_quorum import __version__
from krystal_quorum.diff_models import DiffResult, DiffRunManifest, ManifestArtifact
from krystal_quorum.persist import PersistenceError

if TYPE_CHECKING:
    from krystal_quorum.diff_service import ExecutedDiffRun


UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


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
    safe = re.sub(r"\.{2,}", "_", safe).strip("._-") or "reviewer"
    safe = safe[:80].rstrip("._-") or "reviewer"
    if safe.upper() in WINDOWS_RESERVED_NAMES:
        safe = f"{safe}_reviewer"
    if safe != reviewer:
        digest = hashlib.sha256(reviewer.encode("utf-8")).hexdigest()[:8]
        safe = f"{safe}_{digest}"
    return f"{safe}.json"


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _atomic_write(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except OSError:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _table_text(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _evidence_text(evidence: list[str]) -> str:
    if not evidence:
        return "not present in diff"
    visible = [_table_text(item) for item in evidence[:3]]
    if len(evidence) > 3:
        visible.append(f"and {len(evidence) - 3} more")
    return "<br>".join(visible)


def _build_summary(
    executed: ExecutedDiffRun,
    result: DiffResult,
    run_dir: Path,
    artifact_paths: list[str],
) -> str:
    prepared = executed.prepared
    git = result.git
    diversity = prepared.diversity
    lines = [
        "# Krystal Quorum Diff Review\n\n",
        f"Verdict: **{result.verdict.value}**\n\n",
        f"Plan provenance: `{result.plan_provenance.value}`\n\n",
        "## Git Baseline\n\n",
        f"- Base: `{git.base_ref}` at `{git.base_sha}`\n",
        f"- Head: `{git.head_ref or 'working tree'}` at `{git.head_sha}`\n",
        f"- Merge base: `{git.merge_base_sha or 'not applicable'}`\n",
        f"- Comparison: `{'working tree' if git.working_tree else 'committed refs'}`\n\n",
        "## Quorum And Diversity\n\n",
        f"- Health: `{result.quorum.health.value}`\n",
        f"- Usable reviewers: `{result.quorum.usable_reviewers}` of "
        f"`{result.quorum.total_reviewers}`\n",
        f"- Distinct families: `{result.quorum.distinct_families}`\n",
        f"- Agreement ratio: `{result.quorum.agreement_ratio:.2f}`\n",
        f"- Diversity: `{diversity.status}`\n",
    ]
    if diversity.reason:
        lines.append(f"- Diversity detail: {_table_text(diversity.reason)}\n")

    lines.extend(
        [
            "\n## Commitment Coverage\n\n",
            "| ID | Status | Corroborated | Evidence |\n",
            "| --- | --- | --- | --- |\n",
        ]
    )
    for item in result.coverage:
        lines.append(
            f"| {_table_text(item.commitment_id)} | {item.status.value} | "
            f"{'yes' if item.corroborated else 'no'} | {_evidence_text(item.evidence)} |\n"
        )

    lines.append("\n## Unplanned Scope Findings\n\n")
    if result.scope_findings:
        for finding in result.scope_findings:
            evidence = _evidence_text([finding.evidence] if finding.evidence else [])
            lines.append(
                f"- **{finding.risk.value} / {finding.category.value}**: "
                f"{_table_text(finding.claim)} Evidence: {evidence}.\n"
            )
    else:
        lines.append("- None.\n")

    abstained = sorted(
        {
            output.reviewer
            for output in (*executed.round1_outputs, *executed.round2_outputs)
            if output.verdict.value == "ABSTAIN"
        }
    )
    lines.extend(
        [
            "\n## Abstentions And Contradictions\n\n",
            f"- Abstained reviewers: `{', '.join(abstained) if abstained else 'none'}`\n",
            f"- Contradictions: `{result.quorum.contradiction_count}`\n",
            "\n## Human Triage\n\n",
        ]
    )
    if result.unresolved_for_human:
        lines.extend(f"- {_table_text(item)}\n" for item in result.unresolved_for_human)
    else:
        lines.append("- No unresolved items.\n")

    lines.extend(
        [
            "\n## Artifacts\n\n",
            f"- Output directory: `{run_dir}`\n",
            *(f"- `{path}`\n" for path in artifact_paths),
        ]
    )
    return "".join(lines)


def persist_diff_run(executed: ExecutedDiffRun) -> tuple[Path, DiffResult]:
    """Persist one completed diff run and return its run-specific result."""
    prepared = executed.prepared
    run_dir: Path | None = None
    try:
        run_dir = _run_dir(prepared.options.out_dir, prepared.plan_path)
        result = executed.result.model_copy(update={"output_dir": str(run_dir)})
        artifacts: dict[str, bytes] = {
            "plan_input.md": prepared.plan_text.encode("utf-8"),
            "plan_input.sha256": f"{result.plan.sha256}\n".encode("ascii"),
            "diff_input.patch": prepared.snapshot.patch.encode("utf-8"),
            "diff_input.sha256": f"{result.diff.sha256}\n".encode("ascii"),
            "changed_files.json": _json_bytes(
                [item.model_dump(mode="json") for item in prepared.evidence_files]
            ),
            "review_input.md": prepared.review_input.encode("utf-8"),
            "review_input.sha256": f"{result.review_input_sha256}\n".encode("ascii"),
            "coverage.json": _json_bytes(
                [item.model_dump(mode="json") for item in result.coverage]
            ),
            "reconciled.json": _json_bytes(result.model_dump(mode="json")),
        }
        if prepared.approval_receipt is not None:
            artifacts["approval.json"] = _json_bytes(
                prepared.approval_receipt.model_dump(mode="json")
            )
        for round_name, outputs in (
            ("round1", executed.round1_outputs),
            ("round2", executed.round2_outputs),
        ):
            for output in outputs:
                artifacts[f"{round_name}/{_reviewer_filename(output.reviewer)}"] = _json_bytes(
                    output.model_dump(mode="json")
                )

        artifact_paths = sorted([*artifacts, "manifest.json", "summary.md"])
        artifacts["summary.md"] = _build_summary(
            executed,
            result,
            run_dir,
            artifact_paths,
        ).encode("utf-8")

        for relative_path, payload in artifacts.items():
            destination = run_dir / relative_path
            _atomic_write(destination, payload)

        specs = list(prepared.reviewer_specs)
        manifest = DiffRunManifest(
            schema_version="krystal-quorum.diff.v1",
            tool_version=__version__,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            plan_provenance=result.plan_provenance,
            plan=result.plan,
            git=result.git,
            diff=result.diff,
            review_input_sha256=result.review_input_sha256,
            reviewers_used=[spec.reviewer_id for spec in specs],
            reviewer_families=[spec.family for spec in specs],
            data_boundaries={
                spec.reviewer_id: spec.data_boundary.value for spec in specs
            },
            artifacts=[
                ManifestArtifact(
                    path=relative_path,
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
                for relative_path, payload in sorted(artifacts.items())
            ],
        )
        _atomic_write(
            run_dir / "manifest.json",
            _json_bytes(manifest.model_dump(mode="json")),
        )
    except OSError as exc:
        raise PersistenceError(f"Could not persist diff review artifacts: {exc}", run_dir) from exc
    return run_dir, result
