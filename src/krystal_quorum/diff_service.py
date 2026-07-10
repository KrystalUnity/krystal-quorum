from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from krystal_quorum.approval import (
    ApprovalReceipt,
    canonical_json_sha256,
    load_and_validate_approval,
)
from krystal_quorum.commitments import Commitment, extract_commitments
from krystal_quorum.diff_models import (
    DiffChangedFile,
    DiffEvidenceFile,
    DiffManifest,
    DiffResult,
    DiffReviewerOutput,
    GitManifest,
    PlanProvenance,
    PlanManifest,
    QuorumHealth,
    QuorumMetrics,
)
from krystal_quorum.diff_reconcile import reconcile_diff
from krystal_quorum.diffing import (
    DEFAULT_CONTEXT_LINES,
    DEFAULT_MAX_DIFF_CHARS,
    DiffSnapshot,
    capture_diff,
)
from krystal_quorum.diversity import analyze_reviewer_objects
from krystal_quorum.models import DiversityReport, Verdict
from krystal_quorum.reviewer_specs import (
    DataBoundary,
    ReviewerSpec,
    build_reviewers_from_specs,
    parse_reviewer_specs,
)
from krystal_quorum.reviewers.base import ReviewerProtocol
from krystal_quorum.reviewers.diff_base import diff_fallback_output
from krystal_quorum.sensitive_input import (
    scan_sensitive_input,
    summarize_sensitive_findings,
)


DEFAULT_MAX_PLAN_CHARS = 120_000
DEFAULT_MAX_REVIEW_CHARS = 220_000
ROUND1_TIMEOUT_S = 120
ROUND2_TIMEOUT_S = 180


class DiffServiceError(ValueError):
    """Raised when diff review cannot safely pass preflight or execution."""


@dataclass(frozen=True)
class DiffRunOptions:
    plan: Path
    repo: Path = Path(".")
    approval: Path | None = None
    base: str | None = None
    head: str | None = None
    reviewers: str = "mock"
    config: Path | None = None
    out_dir: Path = Path(".krystal-quorum/reviews")
    round2: bool = False
    require_diversity: bool = False
    max_plan_chars: int = DEFAULT_MAX_PLAN_CHARS
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS
    max_review_chars: int = DEFAULT_MAX_REVIEW_CHARS
    context_lines: int = DEFAULT_CONTEXT_LINES
    include_untracked: bool = True
    allow_secret_looking_input: bool = False
    allow_untracked_external: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class DryRunMetadata:
    plan_sha256: str
    approval_sha256: str | None
    diff_sha256: str
    review_input_sha256: str
    plan_chars: int
    diff_chars: int
    review_input_chars: int
    review_input_rough_tokens: int
    commitment_count: int
    changed_file_count: int
    destinations: tuple[str, ...]
    external_destinations: tuple[str, ...]
    warning_classes: tuple[str, ...]
    warning_counts: dict[str, int]


@dataclass(frozen=True)
class PreparedDiffRun:
    options: DiffRunOptions
    plan_path: Path
    plan_display_path: str
    plan_text: str
    plan_sha256: str
    plan_provenance: PlanProvenance
    approval_receipt: ApprovalReceipt | None
    approval_sha256: str | None
    commitments: tuple[Commitment, ...]
    snapshot: DiffSnapshot
    evidence_files: tuple[DiffEvidenceFile, ...]
    reviewer_specs: tuple[ReviewerSpec, ...]
    diversity: DiversityReport
    review_input: str
    review_input_sha256: str
    review_input_chars: int
    review_input_rough_tokens: int
    secret_warning_classes: tuple[str, ...]
    secret_warning_counts: dict[str, int]
    external_destinations: tuple[str, ...]
    captured_untracked: bool
    dry_run_metadata: DryRunMetadata


@dataclass(frozen=True)
class ExecutedDiffRun:
    prepared: PreparedDiffRun
    round1_outputs: tuple[DiffReviewerOutput, ...]
    round2_outputs: tuple[DiffReviewerOutput, ...]
    result: DiffResult


def _validate_integer(value: int, name: str, *, minimum: int, maximum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "a non-negative integer" if minimum == 0 else "a positive integer"
        raise DiffServiceError(f"{name} must be {qualifier}")
    if maximum is not None and value > maximum:
        raise DiffServiceError(f"{name} must be an integer from {minimum} to {maximum}")


def _validate_options(options: DiffRunOptions) -> None:
    if options.approval is not None and options.base is not None:
        raise DiffServiceError("approval and base cannot be used together")
    if options.approval is None and options.base is None:
        raise DiffServiceError("standalone diff review requires base")
    _validate_integer(options.max_plan_chars, "max_plan_chars", minimum=0)
    _validate_integer(options.max_diff_chars, "max_diff_chars", minimum=1)
    _validate_integer(options.max_review_chars, "max_review_chars", minimum=1)
    _validate_integer(options.context_lines, "context_lines", minimum=0, maximum=200)


def _read_plan(options: DiffRunOptions) -> tuple[Path, str, str]:
    plan_path = options.plan.expanduser().resolve()
    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DiffServiceError(f"Plan must be readable UTF-8: {options.plan}") from exc
    plan_text = plan_text.replace("\r\n", "\n").replace("\r", "\n")
    actual_chars = len(plan_text)
    if options.max_plan_chars and actual_chars > options.max_plan_chars:
        raise DiffServiceError(
            "Plan exceeds max_plan_chars: "
            f"actual_chars={actual_chars}; limit={options.max_plan_chars}; "
            f"rough_tokens={_rough_tokens(actual_chars)}"
        )
    plan_sha256 = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
    return plan_path, plan_text, plan_sha256


def _rough_tokens(characters: int) -> int:
    return (characters + 3) // 4


def _evidence_files(snapshot: DiffSnapshot) -> tuple[DiffEvidenceFile, ...]:
    evidence: list[DiffEvidenceFile] = []
    for changed_file in snapshot.changed_files:
        if changed_file.kind is None:
            raise DiffServiceError(
                f"Changed file metadata is missing an authoritative kind: {changed_file.path}"
            )
        evidence.append(
            DiffEvidenceFile(
                status=changed_file.status,
                path=changed_file.path,
                old_path=changed_file.old_path,
                kind=changed_file.kind,
                source=changed_file.source,
            )
        )
    return tuple(evidence)


def _plan_display_path(
    plan_path: Path,
    snapshot: DiffSnapshot,
    receipt: ApprovalReceipt | None,
) -> str:
    if receipt is not None:
        return receipt.plan_path
    try:
        return plan_path.relative_to(snapshot.repo_root).as_posix()
    except ValueError:
        return plan_path.as_posix()


def _commitment_payload(commitment: Commitment) -> dict[str, Any]:
    return {
        "id": commitment.id,
        "category": commitment.category.value,
        "text": commitment.text,
        "source_line": commitment.source_line,
        "group": commitment.group,
    }


def _build_review_input(
    *,
    plan_path: str,
    plan_text: str,
    plan_sha256: str,
    plan_provenance: PlanProvenance,
    approval_sha256: str | None,
    commitments: tuple[Commitment, ...],
    snapshot: DiffSnapshot,
    evidence_files: tuple[DiffEvidenceFile, ...],
) -> str:
    payload = {
        "review_kind": "diff",
        "plan": {
            "path": plan_path,
            "sha256": plan_sha256,
            "approval_sha256": approval_sha256,
            "provenance": plan_provenance.value,
            "text": plan_text,
        },
        "commitments": [_commitment_payload(item) for item in commitments],
        "git": {
            "base_ref": snapshot.base_ref,
            "base_sha": snapshot.base_sha,
            "head_ref": snapshot.head_ref,
            "head_sha": snapshot.head_sha,
            "merge_base_sha": snapshot.merge_base_sha,
            "comparison": snapshot.comparison,
            "include_untracked": snapshot.include_untracked,
            "working_tree_status": [
                item.model_dump(mode="json") for item in snapshot.working_tree_status
            ],
        },
        "changed_files": [item.model_dump(mode="json") for item in evidence_files],
        "patch": snapshot.patch,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _reviewer_visible_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _reviewer_visible_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _reviewer_visible_strings(item)]
    return []


def _reviewer_diversity(specs: list[ReviewerSpec]) -> DiversityReport:
    metadata = [
        SimpleNamespace(id=spec.reviewer_id, family=spec.family)
        for spec in specs
    ]
    return analyze_reviewer_objects(metadata)


def prepare_diff_run(options: DiffRunOptions) -> PreparedDiffRun:
    """Perform ordered diff preflight without constructing reviewer clients."""
    _validate_options(options)
    plan_path, plan_text, plan_sha256 = _read_plan(options)
    commitments = tuple(extract_commitments(plan_text))
    if not commitments:
        raise DiffServiceError("Plan has no required commitments for diff review")

    receipt: ApprovalReceipt | None = None
    approval_sha256: str | None = None
    if options.approval is not None:
        receipt = load_and_validate_approval(
            options.approval,
            plan_path,
            options.repo,
            head_sha=options.head,
        )
        approval_sha256 = canonical_json_sha256(receipt)
        plan_provenance = PlanProvenance.VERIFIED_RECEIPT
        base_ref = receipt.base_sha
        verified_base = True
    else:
        plan_provenance = PlanProvenance.UNVERIFIED_REFERENCE
        base_ref = options.base
        verified_base = False
    assert base_ref is not None

    snapshot = capture_diff(
        options.repo,
        base_ref=base_ref,
        head_ref=options.head,
        verified_base=verified_base,
        include_untracked=options.include_untracked,
        max_diff_chars=options.max_diff_chars,
        context_lines=options.context_lines,
    )
    evidence_files = _evidence_files(snapshot)
    display_path = _plan_display_path(plan_path, snapshot, receipt)
    review_input = _build_review_input(
        plan_path=display_path,
        plan_text=plan_text,
        plan_sha256=plan_sha256,
        plan_provenance=plan_provenance,
        approval_sha256=approval_sha256,
        commitments=commitments,
        snapshot=snapshot,
        evidence_files=evidence_files,
    )
    review_input_chars = len(review_input)
    review_input_rough_tokens = _rough_tokens(review_input_chars)
    if review_input_chars > options.max_review_chars:
        raise DiffServiceError(
            "Complete reviewer input exceeds max_review_chars: "
            f"actual_chars={review_input_chars}; limit={options.max_review_chars}; "
            f"rough_tokens={review_input_rough_tokens}"
        )
    review_input_sha256 = hashlib.sha256(review_input.encode("utf-8")).hexdigest()

    reviewer_specs = parse_reviewer_specs(options.reviewers, config_path=options.config)
    hosted = [spec.reviewer_id for spec in reviewer_specs if spec.backend == "hosted"]
    if hosted:
        raise DiffServiceError(
            f"hosted diff review is unsupported in v0.7: {', '.join(hosted)}"
        )
    unknown = [
        spec.reviewer_id
        for spec in reviewer_specs
        if spec.data_boundary == DataBoundary.UNKNOWN
    ]
    if unknown:
        raise DiffServiceError(
            f"unknown data boundary for diff reviewer: {', '.join(unknown)}"
        )

    diversity = _reviewer_diversity(reviewer_specs)
    if options.require_diversity and diversity.status != "ok":
        raise DiffServiceError(
            f"reviewer diversity requirement failed: {diversity.reason or 'low diversity'}"
        )

    external_destinations = tuple(
        spec.reviewer_id
        for spec in reviewer_specs
        if spec.data_boundary == DataBoundary.EXTERNAL
    )
    scan_text = "\n".join(_reviewer_visible_strings(json.loads(review_input)))
    sensitive_findings = scan_sensitive_input(scan_text)
    warning_counts = summarize_sensitive_findings(sensitive_findings)
    warning_classes = tuple(warning_counts)
    captured_untracked = any(item.source == "untracked" for item in evidence_files)
    if external_destinations and warning_counts and not options.allow_secret_looking_input:
        raise DiffServiceError(
            "External reviewers require allow_secret_looking_input when likely secrets are present"
        )
    if external_destinations and captured_untracked and not options.allow_untracked_external:
        raise DiffServiceError(
            "External reviewers require allow_untracked_external for captured untracked content"
        )

    dry_run_metadata = DryRunMetadata(
        plan_sha256=plan_sha256,
        approval_sha256=approval_sha256,
        diff_sha256=snapshot.diff_sha256,
        review_input_sha256=review_input_sha256,
        plan_chars=len(plan_text),
        diff_chars=len(snapshot.patch),
        review_input_chars=review_input_chars,
        review_input_rough_tokens=review_input_rough_tokens,
        commitment_count=len(commitments),
        changed_file_count=len(evidence_files),
        destinations=tuple(spec.reviewer_id for spec in reviewer_specs),
        external_destinations=external_destinations,
        warning_classes=warning_classes,
        warning_counts=warning_counts,
    )
    return PreparedDiffRun(
        options=options,
        plan_path=plan_path,
        plan_display_path=display_path,
        plan_text=plan_text,
        plan_sha256=plan_sha256,
        plan_provenance=plan_provenance,
        approval_receipt=receipt,
        approval_sha256=approval_sha256,
        commitments=commitments,
        snapshot=snapshot,
        evidence_files=evidence_files,
        reviewer_specs=tuple(reviewer_specs),
        diversity=diversity,
        review_input=review_input,
        review_input_sha256=review_input_sha256,
        review_input_chars=review_input_chars,
        review_input_rough_tokens=review_input_rough_tokens,
        secret_warning_classes=warning_classes,
        secret_warning_counts=warning_counts,
        external_destinations=external_destinations,
        captured_untracked=captured_untracked,
        dry_run_metadata=dry_run_metadata,
    )


async def _review_round1(
    reviewer: ReviewerProtocol,
    prepared: PreparedDiffRun,
) -> DiffReviewerOutput:
    try:
        return await reviewer.review_diff_round1(
            prepared.review_input,
            prepared.commitments,
            prepared.evidence_files,
            timeout_s=ROUND1_TIMEOUT_S,
        )
    except Exception as exc:
        return diff_fallback_output(
            reviewer.id,
            1,
            prepared.commitments,
            claim="reviewer transport failed",
            evidence=type(exc).__name__,
        )


async def _review_round2(
    reviewer: ReviewerProtocol,
    prepared: PreparedDiffRun,
    round1_outputs: tuple[DiffReviewerOutput, ...],
) -> DiffReviewerOutput:
    try:
        return await reviewer.review_diff_round2(
            prepared.review_input,
            prepared.commitments,
            prepared.evidence_files,
            list(round1_outputs),
            timeout_s=ROUND2_TIMEOUT_S,
        )
    except Exception as exc:
        return diff_fallback_output(
            reviewer.id,
            2,
            prepared.commitments,
            claim="reviewer transport failed",
            evidence=type(exc).__name__,
        )


def _reconcile(
    prepared: PreparedDiffRun,
    round1_outputs: tuple[DiffReviewerOutput, ...],
    round2_outputs: tuple[DiffReviewerOutput, ...],
) -> DiffResult:
    snapshot = prepared.snapshot
    base_ref = (
        prepared.approval_receipt.base_ref
        if prepared.approval_receipt is not None
        else snapshot.base_ref
    )
    changed_files = [
        DiffChangedFile(status=item.status, path=item.path, old_path=item.old_path)
        for item in prepared.evidence_files
    ]
    return reconcile_diff(
        commitments=prepared.commitments,
        round1_outputs=round1_outputs,
        round2_outputs=round2_outputs,
        reviewer_specs=prepared.reviewer_specs,
        plan_provenance=prepared.plan_provenance,
        plan_path=prepared.plan_display_path,
        plan_sha256=prepared.plan_sha256,
        approval_sha256=prepared.approval_sha256,
        base_ref=base_ref,
        base_sha=snapshot.base_sha,
        head_ref=snapshot.head_ref,
        head_sha=snapshot.head_sha,
        merge_base_sha=snapshot.merge_base_sha,
        working_tree=snapshot.comparison == "working_tree",
        diff_sha256=snapshot.diff_sha256,
        changed_files=changed_files,
        review_input_sha256=prepared.review_input_sha256,
        output_dir=str(prepared.options.out_dir),
    )


def _reconciliation_failure_result(
    prepared: PreparedDiffRun,
    exc: Exception,
) -> DiffResult:
    snapshot = prepared.snapshot
    base_ref = (
        prepared.approval_receipt.base_ref
        if prepared.approval_receipt is not None
        else snapshot.base_ref
    )
    return DiffResult(
        schema_version="krystal-quorum.diff.v1",
        review_kind="diff",
        verdict=Verdict.ABSTAIN,
        plan_provenance=prepared.plan_provenance,
        plan=PlanManifest(
            path=prepared.plan_display_path,
            sha256=prepared.plan_sha256,
            approval_sha256=prepared.approval_sha256,
        ),
        git=GitManifest(
            base_ref=base_ref,
            base_sha=snapshot.base_sha,
            head_ref=snapshot.head_ref,
            head_sha=snapshot.head_sha,
            merge_base_sha=snapshot.merge_base_sha,
            working_tree=snapshot.comparison == "working_tree",
        ),
        diff=DiffManifest(
            sha256=snapshot.diff_sha256,
            changed_files=[
                DiffChangedFile(status=item.status, path=item.path, old_path=item.old_path)
                for item in prepared.evidence_files
            ],
        ),
        review_input_sha256=prepared.review_input_sha256,
        quorum=QuorumMetrics(
            health=QuorumHealth.COLLAPSED,
            usable_reviewers=0,
            total_reviewers=len(prepared.reviewer_specs),
            distinct_families=0,
            agreement_ratio=0.0,
            contradiction_count=0,
        ),
        reviewers_used=[spec.reviewer_id for spec in prepared.reviewer_specs],
        coverage=[],
        scope_findings=[],
        unresolved_for_human=[
            "Diff reconciliation failed after reviewer execution began "
            f"({type(exc).__name__}); reviewer outputs were preserved for audit."
        ],
        output_dir=str(prepared.options.out_dir),
    )


async def execute_diff_run(prepared: PreparedDiffRun) -> ExecutedDiffRun:
    """Construct reviewers, preserve both rounds, and reconcile valid audit state."""
    if prepared.options.dry_run:
        raise DiffServiceError("dry-run preflight cannot be executed")
    reviewer_execution_started = False
    if not prepared.snapshot.patch:
        round1_outputs: tuple[DiffReviewerOutput, ...] = ()
        round2_outputs: tuple[DiffReviewerOutput, ...] = ()
    else:
        reviewers = build_reviewers_from_specs(list(prepared.reviewer_specs))
        reviewer_execution_started = True
        round1_outputs = tuple(
            await asyncio.gather(
                *(_review_round1(reviewer, prepared) for reviewer in reviewers)
            )
        )
        round2_outputs = ()
        if prepared.options.round2:
            round2_outputs = tuple(
                await asyncio.gather(
                    *(
                        _review_round2(reviewer, prepared, round1_outputs)
                        for reviewer in reviewers
                    )
                )
            )

    try:
        result = _reconcile(prepared, round1_outputs, round2_outputs)
    except Exception as exc:
        if not reviewer_execution_started:
            raise
        result = _reconciliation_failure_result(prepared, exc)
    else:
        outputs = (*round1_outputs, *round2_outputs)
        if any(output.verdict == Verdict.ABSTAIN for output in outputs):
            result = result.model_copy(update={"verdict": Verdict.ABSTAIN})
    return ExecutedDiffRun(
        prepared=prepared,
        round1_outputs=round1_outputs,
        round2_outputs=round2_outputs,
        result=result,
    )
