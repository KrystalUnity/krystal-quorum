from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
import re
from typing import Any

from krystal_quorum.diff_models import (
    DIFF_SCHEMA_VERSION,
    AggregatedCoverageItem,
    CoverageStatus,
    DiffChangedFile,
    DiffCoverageItem,
    DiffManifest,
    DiffReviewerOutput,
    DiffResult,
    GitManifest,
    PlanManifest,
    PlanProvenance,
    QuorumHealth,
    QuorumMetrics,
    ScopeCategory,
    ScopeFinding,
    ScopeRisk,
)
from krystal_quorum.models import Verdict
from krystal_quorum.reviewer_specs import ReviewerSpec
from krystal_quorum.reviewers.diff_base import expected_commitment_ids


MAX_EVIDENCE_ITEMS = 5
MAX_EVIDENCE_LENGTH = 500
MAX_DIAGNOSTIC_ITEMS = 100
MAX_DIAGNOSTIC_LENGTH = 500

_ADVERSE_CONTRADICTION_STATUSES = {
    CoverageStatus.MISSING,
    CoverageStatus.PARTIAL,
    CoverageStatus.NOT_EVIDENT,
}
_STATUS_PRIORITY = {
    CoverageStatus.IMPLEMENTED: 0,
    CoverageStatus.NA: 1,
    CoverageStatus.NOT_EVIDENT: 2,
    CoverageStatus.PARTIAL: 3,
    CoverageStatus.MISSING: 4,
}
_VERDICT_PRIORITY = {
    Verdict.ABSTAIN: 0,
    Verdict.APPROVE: 1,
    Verdict.REVISE: 2,
    Verdict.BLOCK: 3,
}
_CLAIM_WORD = re.compile(r"[a-z0-9]+")
_GENERIC_SCOPE_CATEGORIES = {
    ScopeCategory.FEATURE,
    ScopeCategory.DEPENDENCY,
    ScopeCategory.CONFIGURATION,
    ScopeCategory.TEST,
    ScopeCategory.DOCUMENTATION,
    ScopeCategory.REFACTOR,
    ScopeCategory.OBSERVABILITY,
    ScopeCategory.PERFORMANCE,
    ScopeCategory.OTHER,
}
_OPERATION_POLARITY = {
    "add": 1,
    "added": 1,
    "adding": 1,
    "adds": 1,
    "introduce": 1,
    "introduced": 1,
    "introduces": 1,
    "introducing": 1,
    "remove": -1,
    "removed": -1,
    "removes": -1,
    "removing": -1,
}
_NEGATIONS = {"no", "not", "never", "without"}
_CLAIM_ANCHOR_ALIASES = {
    token: anchor
    for anchor, tokens in {
        "credential": {"credential", "credentials", "secret", "secrets", "token", "tokens"},
        "log-output": {"diagnostic", "diagnostics", "log", "logged", "logging", "logs", "output"},
    }.items()
    for token in tokens
}
_CLAIM_STOP_WORDS = {
    "about",
    "after",
    "also",
    "are",
    "before",
    "being",
    "behavior",
    "changed",
    "changes",
    "code",
    "feature",
    "finding",
    "from",
    "into",
    "issue",
    "operation",
    "risk",
    "scope",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "unplanned",
    "value",
    "values",
    "with",
}


@dataclass(frozen=True)
class _CoverageAggregate:
    item: AggregatedCoverageItem
    counts: Counter[CoverageStatus]
    contradiction: bool
    unique_mode: bool


@dataclass
class _ScopeGroup:
    members: list[tuple[str, ScopeFinding]]

    @property
    def reviewers(self) -> set[str]:
        return {reviewer for reviewer, _ in self.members}

    @property
    def corroborated(self) -> bool:
        return len(self.reviewers) >= 2

    @property
    def high_risk(self) -> bool:
        return any(finding.risk == ScopeRisk.HIGH for _, finding in self.members)


def _bounded(value: str, limit: int) -> str:
    return value[:limit]


def _append_diagnostic(diagnostics: list[str], value: str) -> None:
    bounded = _bounded(value, MAX_DIAGNOSTIC_LENGTH)
    if bounded not in diagnostics and len(diagnostics) < MAX_DIAGNOSTIC_ITEMS:
        diagnostics.append(bounded)


def _distinct_specs(reviewer_specs: Sequence[ReviewerSpec]) -> list[ReviewerSpec]:
    distinct: dict[str, ReviewerSpec] = {}
    for spec in reviewer_specs:
        distinct.setdefault(spec.reviewer_id, spec)
    return list(distinct.values())


def _output_priority(output: DiffReviewerOutput) -> tuple[int, int, int, int, int, str]:
    coverage_priority = max(
        (_STATUS_PRIORITY[item.status] for item in output.commitment_coverage),
        default=-1,
    )
    return (
        output.round,
        int(output.verdict != Verdict.ABSTAIN),
        coverage_priority,
        int(any(finding.risk == ScopeRisk.HIGH for finding in output.scope_findings)),
        _VERDICT_PRIORITY[output.verdict],
        output.model_dump_json(),
    )


def _effective_outputs(
    round1_outputs: Sequence[DiffReviewerOutput],
    round2_outputs: Sequence[DiffReviewerOutput],
    specs: Sequence[ReviewerSpec],
) -> list[DiffReviewerOutput]:
    reviewer_order = [spec.reviewer_id for spec in specs]
    known_reviewers = set(reviewer_order)
    candidates: dict[str, list[DiffReviewerOutput]] = {}
    for output in [*round1_outputs, *round2_outputs]:
        if output.reviewer not in known_reviewers:
            raise ValueError(f"reviewer output has no matching reviewer spec: {output.reviewer}")
        candidates.setdefault(output.reviewer, []).append(output)

    effective: list[DiffReviewerOutput] = []
    for reviewer in reviewer_order:
        reviewer_candidates = candidates.get(reviewer, [])
        if reviewer_candidates:
            effective.append(max(reviewer_candidates, key=_output_priority))
    return effective


def _validate_coverage(
    outputs: Sequence[DiffReviewerOutput],
    commitment_ids: Sequence[str],
) -> None:
    expected = Counter(commitment_ids)
    for output in outputs:
        if output.verdict == Verdict.ABSTAIN:
            continue
        actual = Counter(item.commitment_id for item in output.commitment_coverage)
        if actual != expected or len(output.commitment_coverage) != len(commitment_ids):
            raise ValueError(
                f"reviewer {output.reviewer} must assess every commitment ID exactly once"
            )


def _evidence_text(item: DiffCoverageItem) -> str | None:
    if item.evidence:
        return _bounded(item.evidence, MAX_EVIDENCE_LENGTH)
    if item.path and item.line_start is not None:
        return _bounded(f"{item.path}:{item.line_start}", MAX_EVIDENCE_LENGTH)
    if item.path:
        return _bounded(item.path, MAX_EVIDENCE_LENGTH)
    return None


def _aggregate_commitments(
    commitment_ids: Sequence[str],
    usable_outputs: Sequence[DiffReviewerOutput],
) -> list[_CoverageAggregate]:
    aggregates: list[_CoverageAggregate] = []
    coverage_by_reviewer = {
        output.reviewer: {item.commitment_id: item for item in output.commitment_coverage}
        for output in usable_outputs
    }

    for commitment_id in commitment_ids:
        positions = [
            (output.reviewer, coverage_by_reviewer[output.reviewer][commitment_id])
            for output in usable_outputs
        ]
        counts = Counter(item.status for _, item in positions)
        if counts:
            highest_count = max(counts.values())
            modal_statuses = [status for status, count in counts.items() if count == highest_count]
            status = max(modal_statuses, key=_STATUS_PRIORITY.__getitem__)
            unique_mode = len(modal_statuses) == 1
        else:
            status = CoverageStatus.NOT_EVIDENT
            unique_mode = False

        supporters = [reviewer for reviewer, item in positions if item.status == status]
        evidence: list[str] = []
        for _, item in positions:
            if item.status != status:
                continue
            value = _evidence_text(item)
            if value and value not in evidence and len(evidence) < MAX_EVIDENCE_ITEMS:
                evidence.append(value)

        statuses = set(counts)
        contradiction = CoverageStatus.IMPLEMENTED in statuses and bool(
            statuses & _ADVERSE_CONTRADICTION_STATUSES
        )
        aggregates.append(
            _CoverageAggregate(
                item=AggregatedCoverageItem(
                    commitment_id=commitment_id,
                    status=status,
                    corroborated=len(supporters) >= 2,
                    reviewers=supporters,
                    evidence=evidence,
                ),
                counts=counts,
                contradiction=contradiction,
                unique_mode=unique_mode,
            )
        )
    return aggregates


def _normalized_path(path: str | None) -> str | None:
    if path is None:
        return None
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _claim_words(claim: str) -> list[str]:
    return _CLAIM_WORD.findall(claim.lower().replace("n't", " not"))


def _operation_polarities(claim: str) -> set[int]:
    words = _claim_words(claim)
    polarities: set[int] = set()
    for index, word in enumerate(words):
        polarity = _OPERATION_POLARITY.get(word)
        if polarity is None:
            continue
        if any(token in _NEGATIONS for token in words[max(0, index - 5) : index]):
            polarity *= -1
        polarities.add(polarity)
    return polarities


def _polarity_conflicts(left: str, right: str) -> bool:
    left_polarities = _operation_polarities(left)
    right_polarities = _operation_polarities(right)
    return (1 in left_polarities and -1 in right_polarities) or (
        -1 in left_polarities and 1 in right_polarities
    )


def _claim_anchors(claim: str) -> set[str]:
    anchors: set[str] = set()
    for word in _claim_words(claim):
        alias = _CLAIM_ANCHOR_ALIASES.get(word)
        if alias is not None:
            anchors.add(alias)
        elif (
            len(word) >= 4
            and word not in _CLAIM_STOP_WORDS
            and word not in _OPERATION_POLARITY
            and word not in _NEGATIONS
        ):
            anchors.add(word)
    return anchors


def _shares_semantic_identity(left: ScopeFinding, right: ScopeFinding) -> bool:
    return len(_claim_anchors(left.claim) & _claim_anchors(right.claim)) >= 2


def _same_structured_scope_identity(left: ScopeFinding, right: ScopeFinding) -> bool:
    if left.category != right.category:
        return False
    left_path = _normalized_path(left.path)
    right_path = _normalized_path(right.path)
    if left_path is not None and right_path is not None:
        if left_path != right_path:
            return False
        if left.category not in _GENERIC_SCOPE_CATEGORIES:
            return True
        return _shares_semantic_identity(left, right)
    if left_path is not None or right_path is not None:
        return False
    return _shares_semantic_identity(left, right)


def _scope_findings_match(left: ScopeFinding, right: ScopeFinding) -> bool:
    return _same_structured_scope_identity(left, right) and not _polarity_conflicts(
        left.claim,
        right.claim,
    )


def _bounded_scope_finding(finding: ScopeFinding) -> ScopeFinding:
    return finding.model_copy(
        update={
            "claim": _bounded(finding.claim, MAX_EVIDENCE_LENGTH),
            "evidence": (
                _bounded(finding.evidence, MAX_EVIDENCE_LENGTH)
                if finding.evidence is not None
                else None
            ),
        }
    )


def _group_scope_findings(usable_outputs: Sequence[DiffReviewerOutput]) -> list[_ScopeGroup]:
    groups: list[_ScopeGroup] = []
    for output in usable_outputs:
        for finding in output.scope_findings:
            group = next(
                (
                    candidate
                    for candidate in groups
                    if all(
                        _scope_findings_match(finding, member)
                        for _, member in candidate.members
                    )
                ),
                None,
            )
            if group is None:
                groups.append(_ScopeGroup(members=[(output.reviewer, finding)]))
            else:
                group.members.append((output.reviewer, finding))
    return groups


def _scope_contradictions(
    usable_outputs: Sequence[DiffReviewerOutput],
) -> list[tuple[ScopeCategory, str | None]]:
    findings = [
        (output.reviewer, finding)
        for output in usable_outputs
        for finding in output.scope_findings
    ]
    contradictions: list[tuple[ScopeCategory, str | None]] = []
    seen: set[tuple[ScopeCategory, str | None]] = set()
    for index, (left_reviewer, left) in enumerate(findings):
        for right_reviewer, right in findings[index + 1 :]:
            if left_reviewer == right_reviewer:
                continue
            if not _same_structured_scope_identity(left, right):
                continue
            if not _polarity_conflicts(left.claim, right.claim):
                continue
            key = (left.category, _normalized_path(left.path))
            if key not in seen:
                seen.add(key)
                contradictions.append(key)
    return contradictions


def _quorum_health(usable_reviewers: int, total_reviewers: int) -> QuorumHealth:
    if usable_reviewers == 0:
        return QuorumHealth.COLLAPSED
    if usable_reviewers < 2 or usable_reviewers < total_reviewers:
        return QuorumHealth.DEGRADED
    return QuorumHealth.HEALTHY


def reconcile_diff(
    *,
    commitments: Sequence[Any],
    round1_outputs: Sequence[DiffReviewerOutput],
    round2_outputs: Sequence[DiffReviewerOutput],
    reviewer_specs: Sequence[ReviewerSpec],
    plan_provenance: PlanProvenance,
    plan_path: str,
    plan_sha256: str,
    approval_sha256: str | None,
    base_ref: str,
    base_sha: str,
    head_ref: str | None,
    head_sha: str,
    merge_base_sha: str | None,
    working_tree: bool,
    diff_sha256: str,
    changed_files: Sequence[DiffChangedFile],
    review_input_sha256: str,
    output_dir: str,
) -> DiffResult:
    """Reconcile reviewer evidence without I/O or manufactured confidence."""
    commitment_ids = expected_commitment_ids(commitments)
    specs = _distinct_specs(reviewer_specs)
    effective_outputs = _effective_outputs(round1_outputs, round2_outputs, specs)
    _validate_coverage(effective_outputs, commitment_ids)

    usable_outputs = [
        output for output in effective_outputs if output.verdict != Verdict.ABSTAIN
    ]
    usable_reviewers = {output.reviewer for output in usable_outputs}
    coverage_aggregates = _aggregate_commitments(commitment_ids, usable_outputs)
    scope_groups = _group_scope_findings(usable_outputs)
    scope_contradictions = _scope_contradictions(usable_outputs)

    total = len(specs)
    usable = len(usable_outputs)
    health = _quorum_health(usable, total)
    agreement_ratio = sum(item.unique_mode for item in coverage_aggregates) / len(
        commitment_ids
    )
    contradiction_count = sum(item.contradiction for item in coverage_aggregates) + len(
        scope_contradictions
    )
    distinct_families = len(
        {spec.family for spec in specs if spec.reviewer_id in usable_reviewers}
    )

    diagnostics: list[str] = []
    if health == QuorumHealth.COLLAPSED:
        _append_diagnostic(
            diagnostics,
            "All reviewers abstained or produced no output; no usable review signal was produced.",
        )
    elif usable < total:
        _append_diagnostic(
            diagnostics,
            f"Partial quorum: {total - usable} of {total} reviewers abstained or produced no output.",
        )
    elif usable == 1:
        _append_diagnostic(
            diagnostics,
            "Single usable reviewer: corroboration is unavailable and quorum health is degraded.",
        )

    effective_by_reviewer = {output.reviewer: output for output in effective_outputs}
    for spec in specs:
        output = effective_by_reviewer.get(spec.reviewer_id)
        if output is None:
            _append_diagnostic(diagnostics, f"Reviewer {spec.reviewer_id} produced no output.")
        elif output.verdict == Verdict.ABSTAIN:
            claim = output.blocking_issues[0].claim if output.blocking_issues else "no diagnostic"
            _append_diagnostic(
                diagnostics,
                f"Reviewer {spec.reviewer_id} abstained: {claim}",
            )

    corroborated_missing = False
    corroborated_incomplete = False
    nonimplemented_required = False
    for aggregate in coverage_aggregates:
        commitment_id = aggregate.item.commitment_id
        if aggregate.counts[CoverageStatus.MISSING] >= 2:
            corroborated_missing = True
            _append_diagnostic(
                diagnostics,
                f"Corroborated MISSING commitment {commitment_id}.",
            )
        elif aggregate.counts[CoverageStatus.MISSING] == 1:
            _append_diagnostic(
                diagnostics,
                f"Singleton MISSING commitment {commitment_id}: human triage required.",
            )
        if any(
            aggregate.counts[status] >= 2
            for status in (CoverageStatus.PARTIAL, CoverageStatus.NOT_EVIDENT)
        ):
            corroborated_incomplete = True
            _append_diagnostic(
                diagnostics,
                f"Corroborated incomplete commitment {commitment_id}.",
            )
        if aggregate.contradiction:
            _append_diagnostic(
                diagnostics,
                f"Contradiction on {commitment_id}: human triage required.",
            )
        if aggregate.counts and any(
            status != CoverageStatus.IMPLEMENTED for status in aggregate.counts
        ):
            nonimplemented_required = True
        if aggregate.counts[CoverageStatus.NA]:
            _append_diagnostic(
                diagnostics,
                f"N/A is invalid for required commitment {commitment_id}; human triage required.",
            )

    scope_findings = [_bounded_scope_finding(group.members[0][1]) for group in scope_groups]
    corroborated_high_risk_scope = False
    for group in scope_groups:
        finding = group.members[0][1]
        if group.corroborated and group.high_risk:
            corroborated_high_risk_scope = True
            _append_diagnostic(
                diagnostics,
                f"Corroborated high-risk scope: {finding.claim}",
            )
        else:
            _append_diagnostic(
                diagnostics,
                f"Unresolved scope finding requires human triage: {finding.claim}",
            )

    for category, path in scope_contradictions:
        location = path or "no authoritative path"
        _append_diagnostic(
            diagnostics,
            f"Scope contradiction on {category.value} at {location}: "
            "conflicting operation polarity; human triage required.",
        )

    reviewer_verdict_concern = False
    for output in usable_outputs:
        if output.verdict in {Verdict.REVISE, Verdict.BLOCK}:
            reviewer_verdict_concern = True
        for issue in output.blocking_issues:
            _append_diagnostic(
                diagnostics,
                f"Singleton blocker from {output.reviewer}: {issue.claim}",
            )

    if health == QuorumHealth.COLLAPSED:
        verdict = Verdict.REVISE
    elif corroborated_missing or corroborated_high_risk_scope:
        verdict = Verdict.BLOCK
    elif (
        corroborated_incomplete
        or nonimplemented_required
        or contradiction_count
        or scope_groups
        or reviewer_verdict_concern
    ):
        verdict = Verdict.REVISE
    else:
        verdict = Verdict.APPROVE

    return DiffResult(
        schema_version=DIFF_SCHEMA_VERSION,
        review_kind="diff",
        verdict=verdict,
        plan_provenance=plan_provenance,
        plan=PlanManifest(
            path=plan_path,
            sha256=plan_sha256,
            approval_sha256=approval_sha256,
        ),
        git=GitManifest(
            base_ref=base_ref,
            base_sha=base_sha,
            head_ref=head_ref,
            head_sha=head_sha,
            merge_base_sha=merge_base_sha,
            working_tree=working_tree,
        ),
        diff=DiffManifest(
            sha256=diff_sha256,
            changed_files=[
                item
                if isinstance(item, DiffChangedFile)
                else DiffChangedFile.model_validate(item)
                for item in changed_files
            ],
        ),
        review_input_sha256=review_input_sha256,
        quorum=QuorumMetrics(
            health=health,
            usable_reviewers=usable,
            total_reviewers=total,
            distinct_families=distinct_families,
            agreement_ratio=agreement_ratio,
            contradiction_count=contradiction_count,
        ),
        reviewers_used=[spec.reviewer_id for spec in specs],
        coverage=[aggregate.item for aggregate in coverage_aggregates],
        scope_findings=scope_findings,
        unresolved_for_human=diagnostics,
        output_dir=output_dir,
    )
