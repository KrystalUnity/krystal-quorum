from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from krystal_quorum.models import (
    ClauseStatus,
    ReviewIssue,
    ReviewSuggestion,
    StrictModel,
    Verdict,
)

DIFF_SCHEMA_VERSION = "krystal-quorum.diff.v1"
DIFF_CLAUSE_IDS = (
    "scope.alignment",
    "tests.coverage",
    "security.alignment",
    "dependencies.alignment",
    "rollback.implemented",
    "observability.implemented",
)


class CoverageStatus(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    NOT_EVIDENT = "NOT_EVIDENT"
    NA = "N/A"


class ScopeRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScopeCategory(str, Enum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    PAYMENTS = "payments"
    CREDENTIAL_HANDLING = "credential-handling"
    DESTRUCTIVE_DATA_OPERATION = "destructive-data-operation"
    SCHEMA_MIGRATION = "schema-migration"
    PRODUCTION_DEPENDENCY = "production-dependency"
    DEPLOYMENT_CONFIGURATION = "deployment-configuration"
    FEATURE = "feature"
    DEPENDENCY = "dependency"
    CONFIGURATION = "configuration"
    TEST = "test"
    DOCUMENTATION = "documentation"
    REFACTOR = "refactor"
    OBSERVABILITY = "observability"
    PERFORMANCE = "performance"
    OTHER = "other"


HIGH_RISK_SCOPE_CATEGORIES = frozenset(
    {
        ScopeCategory.AUTHENTICATION,
        ScopeCategory.AUTHORIZATION,
        ScopeCategory.PAYMENTS,
        ScopeCategory.CREDENTIAL_HANDLING,
        ScopeCategory.DESTRUCTIVE_DATA_OPERATION,
        ScopeCategory.SCHEMA_MIGRATION,
        ScopeCategory.PRODUCTION_DEPENDENCY,
        ScopeCategory.DEPLOYMENT_CONFIGURATION,
    }
)


class PlanProvenance(str, Enum):
    VERIFIED_RECEIPT = "verified_receipt"
    UNVERIFIED_REFERENCE = "unverified_reference"


class QuorumHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    COLLAPSED = "collapsed"


class _LocatedEvidence(StrictModel):
    evidence: str | None
    path: str | None
    line_start: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _line_requires_path(self) -> _LocatedEvidence:
        if self.line_start is not None and self.path is None:
            raise ValueError("line_start requires path")
        return self


class DiffCoverageItem(_LocatedEvidence):
    commitment_id: str = Field(min_length=1)
    status: CoverageStatus
    claim: str = Field(min_length=1)


class ScopeFinding(_LocatedEvidence):
    category: ScopeCategory
    risk: ScopeRisk
    claim: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_high_risk_category(self) -> ScopeFinding:
        if self.category in HIGH_RISK_SCOPE_CATEGORIES and self.risk != ScopeRisk.HIGH:
            raise ValueError(f"scope category {self.category.value} requires risk=high")
        return self


class DiffReviewerOutput(StrictModel):
    reviewer: str
    round: Literal[1, 2]
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    commitment_coverage: list[DiffCoverageItem]
    scope_findings: list[ScopeFinding]
    blocking_issues: list[ReviewIssue]
    suggestions: list[ReviewSuggestion]
    per_clause: dict[str, ClauseStatus]
    raw_response: str
    elapsed_seconds: float
    retries: int = Field(default=0, ge=0)

    @field_validator("per_clause")
    @classmethod
    def _require_exact_diff_clauses(
        cls, value: dict[str, ClauseStatus]
    ) -> dict[str, ClauseStatus]:
        if set(value) != set(DIFF_CLAUSE_IDS):
            raise ValueError("per_clause must contain the exact diff clause IDs")
        return value

    @model_validator(mode="after")
    def _validate_verdict_semantics(self) -> DiffReviewerOutput:
        if self.verdict == Verdict.APPROVE:
            if not self.commitment_coverage or any(
                item.status != CoverageStatus.IMPLEMENTED
                for item in self.commitment_coverage
            ):
                raise ValueError("APPROVE requires every commitment to be IMPLEMENTED")
            if self.scope_findings or self.blocking_issues:
                raise ValueError("APPROVE cannot contain scope or blocking findings")
        if self.verdict == Verdict.ABSTAIN:
            if self.confidence != 0:
                raise ValueError("ABSTAIN requires confidence=0")
            if self.commitment_coverage or self.scope_findings or self.suggestions:
                raise ValueError("ABSTAIN requires empty coverage, scope findings, and suggestions")
            if not any(
                issue.section == "runtime" and bool(issue.claim.strip())
                for issue in self.blocking_issues
            ):
                raise ValueError("ABSTAIN requires a nonempty runtime diagnostic issue")
        return self


class DiffEvidenceFile(StrictModel):
    status: Literal["A", "B", "D", "M", "R", "T", "U", "X"]
    path: str = Field(min_length=1)
    old_path: str | None = None
    kind: Literal[
        "text",
        "binary",
        "symlink",
        "submodule",
        "unreadable",
        "fifo",
        "nonregular",
    ]
    source: Literal[
        "tracked",
        "committed",
        "staged",
        "unstaged",
        "working_tree",
        "untracked",
    ]

    @model_validator(mode="after")
    def _validate_rename_fields(self) -> DiffEvidenceFile:
        if self.status == "R" and self.old_path is None:
            raise ValueError("rename evidence requires old_path")
        if self.status != "R" and self.old_path is not None:
            raise ValueError("only rename evidence may include old_path")
        return self


class DiffChangedFile(StrictModel):
    status: Literal["A", "B", "D", "M", "R", "T", "U", "X"]
    path: str = Field(min_length=1)
    old_path: str | None = None

    @model_validator(mode="after")
    def _validate_old_path(self) -> DiffChangedFile:
        if self.status == "R" and self.old_path is None:
            raise ValueError("renamed files require old_path")
        if self.status != "R" and self.old_path is not None:
            raise ValueError("only renamed files may have old_path")
        return self


class PlanManifest(StrictModel):
    path: str = Field(min_length=1)
    sha256: str
    approval_sha256: str | None

    @field_validator("sha256", "approval_sha256")
    @classmethod
    def _validate_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("expected a lowercase SHA256 digest")
        return value


class GitManifest(StrictModel):
    base_ref: str = Field(min_length=1)
    base_sha: str
    head_ref: str | None
    head_sha: str
    merge_base_sha: str | None
    working_tree: bool

    @field_validator("base_sha", "head_sha", "merge_base_sha")
    @classmethod
    def _validate_git_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) not in {40, 64} or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError("expected a full lowercase Git object ID")
        return value


class DiffManifest(StrictModel):
    sha256: str
    changed_files: list[DiffChangedFile]

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("expected a lowercase SHA256 digest")
        return value


class QuorumMetrics(StrictModel):
    health: QuorumHealth
    usable_reviewers: int = Field(ge=0)
    total_reviewers: int = Field(ge=0)
    distinct_families: int = Field(ge=0)
    agreement_ratio: float = Field(ge=0.0, le=1.0)
    contradiction_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_counts(self) -> QuorumMetrics:
        if self.usable_reviewers > self.total_reviewers:
            raise ValueError("usable_reviewers cannot exceed total_reviewers")
        if self.distinct_families > self.usable_reviewers:
            raise ValueError("distinct_families cannot exceed usable_reviewers")
        return self


class AggregatedCoverageItem(StrictModel):
    commitment_id: str = Field(min_length=1)
    status: CoverageStatus
    corroborated: bool
    reviewers: list[str]
    evidence: list[str]


class DiffResult(StrictModel):
    schema_version: Literal["krystal-quorum.diff.v1"]
    review_kind: Literal["diff"]
    verdict: Verdict
    plan_provenance: PlanProvenance
    plan: PlanManifest
    git: GitManifest
    diff: DiffManifest
    review_input_sha256: str
    quorum: QuorumMetrics
    reviewers_used: list[str]
    coverage: list[AggregatedCoverageItem]
    scope_findings: list[ScopeFinding]
    unresolved_for_human: list[str]
    output_dir: str

    @field_validator("review_input_sha256")
    @classmethod
    def _validate_review_input_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("expected a lowercase SHA256 digest")
        return value


class ManifestArtifact(StrictModel):
    path: str = Field(min_length=1)
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("expected a lowercase SHA256 digest")
        return value


class DiffRunManifest(StrictModel):
    schema_version: Literal["krystal-quorum.diff.v1"]
    tool_version: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    plan_provenance: PlanProvenance
    plan: PlanManifest
    git: GitManifest
    diff: DiffManifest
    review_input_sha256: str
    reviewers_used: list[str]
    reviewer_families: list[str]
    data_boundaries: dict[str, Literal["local", "external", "unknown"]]
    artifacts: list[ManifestArtifact]

    @field_validator("review_input_sha256")
    @classmethod
    def _validate_review_input_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("expected a lowercase SHA256 digest")
        return value


# Public aliases keep the nested result and artifact vocabulary explicit for callers.
DiffPlanManifest = PlanManifest
DiffGitManifest = GitManifest
DiffInputManifest = DiffManifest
CoverageAggregate = AggregatedCoverageItem
ArtifactManifest = ManifestArtifact
