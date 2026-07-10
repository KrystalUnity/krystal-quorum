from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any, Literal
import unicodedata

from pydantic import BaseModel, Field, ValidationError, field_validator

from krystal_quorum.commitments import CommitmentError, CommitmentCategory, extract_commitments
from krystal_quorum.models import ReconciledVerdict, StrictModel, Verdict
from krystal_quorum.sensitive_input import scan_sensitive_input

APPROVAL_SCHEMA_VERSION = "krystal-quorum.approval.v1"
APPROVAL_TOOL_VERSION = "0.7.0"
URI_WITH_AUTHORITY = re.compile(
    r"(?i)(?<![\w+.-])[A-Za-z][A-Za-z0-9+.-]*://"
)
PROTOCOL_RELATIVE_REMOTE = re.compile(r"(?<![\w/])//(?=[^/\s])")
SCP_STYLE_REMOTE = re.compile(
    r"(?i)(?<![\w.%+-])[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[^\s]+"
)
WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?i)(?:[A-Z]:[\\/]|\\\\[^\\/\s]+[\\/])"
)
POSIX_ABSOLUTE_PATH = re.compile(r"/(?![/\s])")
HOME_ABSOLUTE_PATH = re.compile(r"~(?:[^\\/\s]+)?[\\/]")
PATH_CONTINUATION_PUNCTUATION = frozenset("._~+-/")


class ApprovalError(ValueError):
    """Raised when repository binding or approval validation fails closed."""


def _is_path_token_boundary(value: str, index: int) -> bool:
    if index == 0:
        return True
    previous = value[index - 1]
    if previous.isspace():
        return True
    if previous in PATH_CONTINUATION_PUNCTUATION:
        return False
    category = unicodedata.category(previous)
    if category[0] in {"L", "N", "M"} or category == "So":
        return False
    return category[0] in {"P", "Z"} or category in {"Sm", "Sc", "Sk"}


def _has_absolute_path_start(value: str) -> bool:
    patterns = (WINDOWS_ABSOLUTE_PATH, POSIX_ABSOLUTE_PATH, HOME_ABSOLUTE_PATH)
    return any(
        _is_path_token_boundary(value, match.start())
        for pattern in patterns
        for match in pattern.finditer(value)
    )


def _forbidden_receipt_content(value: str) -> str | None:
    if scan_sensitive_input(value):
        return "secret-looking value"
    if (
        URI_WITH_AUTHORITY.search(value)
        or PROTOCOL_RELATIVE_REMOTE.search(value)
        or SCP_STYLE_REMOTE.search(value)
    ):
        return "remote URL"
    if _has_absolute_path_start(value):
        return "absolute path"
    return None


def _require_safe_receipt_strings(values: list[str], *, context: str) -> None:
    for value in values:
        forbidden = _forbidden_receipt_content(value)
        if forbidden is not None:
            raise ApprovalError(f"{context} contains forbidden receipt content: {forbidden}")


class ApprovalCommitment(StrictModel):
    id: str
    category: CommitmentCategory
    text: str
    source_line: int = Field(ge=1)

    @field_validator("text")
    @classmethod
    def _validate_safe_text(cls, value: str) -> str:
        forbidden = _forbidden_receipt_content(value)
        if forbidden is not None:
            raise ValueError(f"forbidden receipt content: {forbidden}")
        return value


class ApprovalReceipt(StrictModel):
    schema_version: Literal["krystal-quorum.approval.v1"]
    tool_version: Literal["0.7.0"]
    created_at: str
    authenticity: Literal["unsigned"]
    verdict: Literal["APPROVE"]
    plan_path: str
    plan_sha256: str
    base_ref: Literal["HEAD"]
    base_sha: str
    reviewers_used: list[str] = Field(min_length=1)
    reviewer_families: list[str] = Field(min_length=1)
    diversity: Literal["ok", "low"]
    reconciled_sha256: str
    commitments: list[ApprovalCommitment] = Field(min_length=1)

    @field_validator("reviewers_used", "reviewer_families")
    @classmethod
    def _validate_safe_reviewer_metadata(cls, values: list[str]) -> list[str]:
        for value in values:
            forbidden = _forbidden_receipt_content(value)
            if forbidden is not None:
                raise ValueError(f"forbidden receipt content: {forbidden}")
        return values

    @field_validator("plan_path")
    @classmethod
    def _validate_plan_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or "\\" in value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != value
        ):
            raise ValueError("plan_path must be a normalized repository-relative POSIX path")
        return value

    @field_validator("plan_sha256", "reconciled_sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("expected a lowercase SHA256 digest")
        return value

    @field_validator("base_sha")
    @classmethod
    def _validate_git_sha(cls, value: str) -> str:
        if len(value) not in {40, 64} or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError("expected a full lowercase Git object ID")
        return value


class BoundRepositoryState(StrictModel):
    repo_root: Path
    plan_file: Path
    artifact_dir: Path
    plan_path: str
    plan_sha256: str
    base_ref: Literal["HEAD"]
    base_sha: str
    commitments: tuple[ApprovalCommitment, ...]


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize JSON deterministically for hashes used by approval artifacts."""
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _plan_sha256(plan_text: str) -> str:
    return hashlib.sha256(plan_text.encode("utf-8")).hexdigest()


def _normalize_plan_text(plan_text: str) -> str:
    return plan_text.replace("\r\n", "\n").replace("\r", "\n")


def _completed_git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        shell=False,
    )


def _git_bytes(repo: Path, *args: str) -> bytes:
    completed = _completed_git(repo, *args)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ApprovalError(detail or f"Git command failed: {' '.join(args)}")
    return completed.stdout


def _git_text(repo: Path, *args: str) -> str:
    return _git_bytes(repo, *args).decode("utf-8", errors="strict").strip()


def _repository_root(repo_dir: Path) -> Path:
    candidate = repo_dir.expanduser().resolve()
    if not candidate.is_dir():
        raise ApprovalError(f"Repository not found: {repo_dir}")
    try:
        root = Path(_git_text(candidate, "rev-parse", "--show-toplevel")).resolve()
    except (ApprovalError, UnicodeDecodeError) as exc:
        raise ApprovalError(f"Not a Git repository: {repo_dir}") from exc
    return root


def _relative_path(root: Path, path: Path, *, label: str) -> tuple[Path, str]:
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ApprovalError(f"{label} must be inside the bound repository") from exc
    return resolved, relative.as_posix()


def _resolve_head(repo_root: Path) -> str:
    try:
        return _git_text(repo_root, "rev-parse", "--verify", "HEAD^{commit}").lower()
    except ApprovalError as exc:
        raise ApprovalError("Bound repository must have a committed HEAD") from exc


def _require_tracked_plan(repo_root: Path, base_sha: str, plan_path: str) -> None:
    completed = _completed_git(repo_root, "cat-file", "-e", f"{base_sha}:{plan_path}")
    if completed.returncode != 0:
        raise ApprovalError(f"Plan must be tracked at HEAD: {plan_path}")


def _head_plan_text(repo_root: Path, base_sha: str, plan_path: str) -> str:
    try:
        blob = _git_bytes(repo_root, "cat-file", "blob", f"{base_sha}:{plan_path}")
        return _normalize_plan_text(blob.decode("utf-8", errors="strict"))
    except (ApprovalError, UnicodeDecodeError) as exc:
        raise ApprovalError(f"Plan at HEAD must be readable UTF-8: {plan_path}") from exc


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _git_metadata_dirs(repo_root: Path) -> tuple[Path, ...]:
    git_dir = Path(_git_text(repo_root, "rev-parse", "--absolute-git-dir")).resolve()
    common_value = Path(_git_text(repo_root, "rev-parse", "--git-common-dir"))
    common_dir = (
        common_value.resolve()
        if common_value.is_absolute()
        else (repo_root / common_value).resolve()
    )
    return git_dir, common_dir


def _validate_artifact_dir(repo_root: Path, base_sha: str, artifact_dir: Path) -> Path:
    candidate = Path(os.path.abspath(artifact_dir.expanduser()))
    existing_ancestor = candidate
    while not existing_ancestor.exists() and not existing_ancestor.is_symlink():
        parent = existing_ancestor.parent
        if parent == existing_ancestor:
            break
        existing_ancestor = parent
    if not existing_ancestor.is_dir():
        raise ApprovalError("Artifact output path's nearest existing ancestor must be a directory")

    resolved = candidate.resolve()
    if resolved == repo_root:
        raise ApprovalError("Artifact output directory cannot be the repository root")
    if not _is_within(resolved, repo_root):
        raise ApprovalError("Artifact output directory must be inside the bound repository")
    if any(_is_within(resolved, metadata_dir) for metadata_dir in _git_metadata_dirs(repo_root)):
        raise ApprovalError("Artifact output directory cannot be inside Git metadata")
    if resolved.exists() and not resolved.is_dir():
        raise ApprovalError("Artifact output path must be a directory")

    relative = resolved.relative_to(repo_root).as_posix()
    tracked = _git_bytes(
        repo_root,
        "ls-tree",
        "-r",
        "-z",
        "--name-only",
        base_sha,
        "--",
        f":(top,literal){relative}",
    )
    if tracked:
        raise ApprovalError("Artifact output directory contains a tracked path at HEAD")
    return resolved


def _status_bytes(repo_root: Path, artifact_dir: Path) -> bytes:
    args = ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."]
    artifact_path = artifact_dir.relative_to(repo_root).as_posix()
    args.append(f":(exclude,top,literal){artifact_path}")
    return _git_bytes(repo_root, *args)


def _relative_path_is_within(path: str, parent: str) -> bool:
    path_parts = PurePosixPath(path).parts
    parent_parts = PurePosixPath(parent).parts
    if os.name == "nt":
        path_parts = tuple(part.casefold() for part in path_parts)
        parent_parts = tuple(part.casefold() for part in parent_parts)
    return len(path_parts) >= len(parent_parts) and path_parts[: len(parent_parts)] == parent_parts


def _require_no_hidden_index_flags(repo_root: Path, artifact_dir: Path) -> None:
    artifact_path = artifact_dir.relative_to(repo_root).as_posix()
    records = _git_bytes(repo_root, "ls-files", "-v", "-z").split(b"\0")
    for record in records:
        if not record:
            continue
        if len(record) < 3 or record[1:2] != b" ":
            raise ApprovalError("Could not safely inspect Git index flags")
        tag = record[:1]
        hidden = tag == b"S" or b"a" <= tag <= b"z"
        if not hidden:
            continue
        tracked_path = record[2:].decode("utf-8", errors="surrogateescape")
        if not _relative_path_is_within(tracked_path, artifact_path):
            raise ApprovalError(
                "Cannot prove a clean repository while tracked files use "
                "assume-unchanged or skip-worktree outside the artifact directory; "
                "clear those index flags and retry"
            )


def _require_plan_unchanged(repo_root: Path, plan_path: str) -> None:
    status = _git_bytes(
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        f":(top,literal){plan_path}",
    )
    if status:
        raise ApprovalError("Plan must be unchanged from HEAD in the index and worktree")


def _approval_commitments(plan_text: str) -> tuple[ApprovalCommitment, ...]:
    try:
        extracted = extract_commitments(plan_text)
    except CommitmentError as exc:
        raise ApprovalError(str(exc)) from exc
    if not extracted:
        raise ApprovalError("Bound plan has no required commitments in recognized sections")
    _require_safe_receipt_strings(
        [item.text for item in extracted],
        context="Bound plan commitment",
    )
    return tuple(
        ApprovalCommitment(
            id=item.id,
            category=item.category,
            text=item.text,
            source_line=item.source_line,
        )
        for item in extracted
    )


def prepare_bound_review(
    repo_dir: Path,
    plan_path: Path,
    artifact_dir: Path,
    *,
    plan_text: str | None = None,
) -> BoundRepositoryState:
    """Capture an eligible repository baseline before constructing reviewers."""
    repo_root = _repository_root(repo_dir)
    plan_file, relative_plan = _relative_path(repo_root, plan_path, label="Plan")
    if not plan_file.is_file():
        raise ApprovalError(f"Plan not found: {plan_path}")
    base_sha = _resolve_head(repo_root)
    resolved_artifact_dir = _validate_artifact_dir(repo_root, base_sha, artifact_dir)
    _require_tracked_plan(repo_root, base_sha, relative_plan)
    _require_plan_unchanged(repo_root, relative_plan)

    try:
        current_plan_text = _normalize_plan_text(plan_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ApprovalError(f"Plan must be readable UTF-8: {relative_plan}") from exc
    head_plan_text = _head_plan_text(repo_root, base_sha, relative_plan)
    if current_plan_text != head_plan_text:
        raise ApprovalError("Reviewer-visible plan does not match HEAD plan bytes")
    if plan_text is not None and _normalize_plan_text(plan_text) != current_plan_text:
        raise ApprovalError("Plan changed before review; re-run the bound review")
    _require_no_hidden_index_flags(repo_root, resolved_artifact_dir)
    commitments = _approval_commitments(current_plan_text)
    if _status_bytes(repo_root, resolved_artifact_dir):
        raise ApprovalError(
            "Bound repository must be clean outside the configured artifact output directory"
        )
    if _resolve_head(repo_root) != base_sha:
        raise ApprovalError("Repository HEAD changed while capturing the bound baseline")

    return BoundRepositoryState(
        repo_root=repo_root,
        plan_file=plan_file,
        artifact_dir=resolved_artifact_dir,
        plan_path=relative_plan,
        plan_sha256=_plan_sha256(current_plan_text),
        base_ref="HEAD",
        base_sha=base_sha,
        commitments=commitments,
    )


def revalidate_bound_review(state: BoundRepositoryState) -> BoundRepositoryState:
    """Re-run repository checks after review and require the original snapshot."""
    try:
        current = prepare_bound_review(state.repo_root, state.plan_file, state.artifact_dir)
    except ApprovalError as exc:
        raise ApprovalError(f"Repository changed during review: {exc}") from exc
    if (
        current.base_sha != state.base_sha
        or current.plan_sha256 != state.plan_sha256
        or current.plan_path != state.plan_path
        or current.commitments != state.commitments
    ):
        raise ApprovalError("Repository changed during review; re-run the bound review")
    return current


def build_approval_receipt(
    state: BoundRepositoryState,
    result: ReconciledVerdict,
    *,
    reconciled_payload: dict[str, Any] | None = None,
) -> ApprovalReceipt:
    """Build an unsigned receipt for an eligible APPROVE reconciliation."""
    if result.merged_verdict != Verdict.APPROVE:
        raise ApprovalError("Approval receipts require an APPROVE verdict")
    reviewer_families = [reviewer.family for reviewer in result.diversity.reviewers]
    _require_safe_receipt_strings(
        [commitment.text for commitment in state.commitments],
        context="Approval commitment",
    )
    _require_safe_receipt_strings(
        [*result.reviewers_used, *reviewer_families],
        context="Reviewer metadata",
    )
    payload = (
        reconciled_payload
        if reconciled_payload is not None
        else result.model_dump(mode="json")
    )
    if payload.get("merged_verdict") != Verdict.APPROVE.value:
        raise ApprovalError("Approval receipts require an APPROVE reconciliation payload")
    return ApprovalReceipt(
        schema_version=APPROVAL_SCHEMA_VERSION,
        tool_version=APPROVAL_TOOL_VERSION,
        created_at=result.timestamp,
        authenticity="unsigned",
        verdict="APPROVE",
        plan_path=state.plan_path,
        plan_sha256=state.plan_sha256,
        base_ref="HEAD",
        base_sha=state.base_sha,
        reviewers_used=list(result.reviewers_used),
        reviewer_families=reviewer_families,
        diversity=result.diversity.status,
        reconciled_sha256=canonical_json_sha256(payload),
        commitments=list(state.commitments),
    )


def _load_json(path: Path, *, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ApprovalError(f"Missing {label}: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApprovalError(f"Invalid {label}: {path}") from exc


def _resolve_commit(repo_root: Path, value: str, *, label: str) -> str:
    try:
        return _git_text(repo_root, "rev-parse", "--verify", f"{value}^{{commit}}").lower()
    except ApprovalError as exc:
        raise ApprovalError(f"Approval {label} is not a commit in the target repository") from exc


def _require_ancestor(repo_root: Path, base_sha: str, head_sha: str) -> None:
    completed = _completed_git(repo_root, "merge-base", "--is-ancestor", base_sha, head_sha)
    if completed.returncode == 1:
        raise ApprovalError(
            "Approval baseline is not an ancestor of the requested implementation head"
        )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ApprovalError(detail or "Could not validate approval baseline ancestry")


def load_and_validate_approval(
    approval_path: Path,
    plan_path: Path,
    repo_dir: Path,
    *,
    head_sha: str | None = None,
) -> ApprovalReceipt:
    """Load an unsigned approval receipt and validate all local audit links."""
    approval_file = approval_path.expanduser().resolve()
    payload = _load_json(approval_file, label="approval receipt")
    try:
        receipt = ApprovalReceipt.model_validate(payload)
    except ValidationError as exc:
        raise ApprovalError(f"Invalid approval receipt: {approval_file}") from exc

    reconciled_path = approval_file.parent / "reconciled.json"
    if not reconciled_path.is_file():
        raise ApprovalError("Missing sibling reconciled.json for approval receipt")
    reconciled = _load_json(reconciled_path, label="sibling reconciled.json")
    if canonical_json_sha256(reconciled) != receipt.reconciled_sha256:
        raise ApprovalError("Approval reconciled hash does not match sibling reconciled.json")
    if not isinstance(reconciled, dict) or reconciled.get("merged_verdict") != "APPROVE":
        raise ApprovalError("Sibling reconciled.json must have an APPROVE verdict")
    reconciled_diversity = reconciled.get("diversity")
    if not isinstance(reconciled_diversity, dict):
        raise ApprovalError("Sibling reconciliation is missing reviewer diversity metadata")
    reconciled_reviewers = reconciled_diversity.get("reviewers")
    if not isinstance(reconciled_reviewers, list):
        raise ApprovalError("Sibling reconciliation is missing reviewer family metadata")
    reconciled_families = [
        reviewer.get("family") if isinstance(reviewer, dict) else None
        for reviewer in reconciled_reviewers
    ]
    if (
        reconciled.get("timestamp") != receipt.created_at
        or reconciled.get("plan_sha256") != receipt.plan_sha256
        or reconciled.get("reviewers_used") != receipt.reviewers_used
        or reconciled_families != receipt.reviewer_families
        or reconciled_diversity.get("status") != receipt.diversity
    ):
        raise ApprovalError(
            "Approval receipt metadata does not match the sibling reconciliation"
        )

    repo_root = _repository_root(repo_dir)
    plan_file, relative_plan = _relative_path(repo_root, plan_path, label="Plan")
    if relative_plan != receipt.plan_path:
        raise ApprovalError("Approval plan path does not match the requested plan")
    try:
        plan_text = plan_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ApprovalError(f"Plan must be readable UTF-8: {relative_plan}") from exc
    if _plan_sha256(plan_text) != receipt.plan_sha256:
        raise ApprovalError("Approval plan hash does not match the current plan")
    if list(_approval_commitments(plan_text)) != receipt.commitments:
        raise ApprovalError("Approval commitments do not match the current plan")

    base_sha = _resolve_commit(repo_root, receipt.base_sha, label="baseline")
    if base_sha != receipt.base_sha:
        raise ApprovalError("Approval baseline must use a full immutable Git object ID")
    try:
        baseline_plan = _head_plan_text(repo_root, base_sha, receipt.plan_path)
    except ApprovalError as exc:
        raise ApprovalError("Approval baseline does not contain the approved UTF-8 plan") from exc
    if _plan_sha256(baseline_plan) != receipt.plan_sha256:
        raise ApprovalError("Approval baseline plan does not match the approved plan hash")

    target_sha = _resolve_commit(
        repo_root,
        head_sha if head_sha is not None else "HEAD",
        label="implementation head",
    )
    _require_ancestor(repo_root, base_sha, target_sha)
    return receipt
