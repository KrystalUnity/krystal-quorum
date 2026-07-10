from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import subprocess
from typing import Literal

from pydantic import Field, field_validator, model_validator

from krystal_quorum.models import StrictModel

DEFAULT_MAX_DIFF_CHARS = 160_000
DEFAULT_CONTEXT_LINES = 20
READ_CHUNK_BYTES = 64 * 1024
PATCH_FLAGS = (
    "--find-renames",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--full-index",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "--submodule=short",
    "--ignore-submodules=none",
    "--diff-algorithm=myers",
    "--no-indent-heuristic",
    "-l1000",
    "-O/dev/null",
)

ChangeStatus = Literal["A", "B", "D", "M", "R", "T", "U", "X"]
ChangeSource = Literal[
    "tracked",
    "committed",
    "staged",
    "unstaged",
    "working_tree",
    "untracked",
]
FileKind = Literal[
    "text",
    "binary",
    "symlink",
    "submodule",
    "unreadable",
    "fifo",
    "nonregular",
]


class DiffCaptureError(ValueError):
    """Raised when Git provenance or bounded diff capture cannot be proven safe."""


class ChangedFile(StrictModel):
    """One NUL-safe changed path and the capture layer that reported it."""

    status: ChangeStatus
    path: str = Field(min_length=1)
    old_path: str | None = None
    similarity: int | None = Field(default=None, ge=0, le=100)
    source: ChangeSource = "tracked"
    kind: FileKind | None = None

    @model_validator(mode="after")
    def _validate_rename_fields(self) -> ChangedFile:
        if self.status == "R":
            if self.old_path is None or self.similarity is None:
                raise ValueError("rename changes require old_path and similarity")
        elif self.old_path is not None or self.similarity is not None:
            raise ValueError("only rename changes may include old_path or similarity")
        return self


class WorkingTreeStatus(StrictModel):
    """Index/worktree porcelain status kept separate from the canonical diff union."""

    index_status: str = Field(min_length=1, max_length=1)
    worktree_status: str = Field(min_length=1, max_length=1)
    path: str = Field(min_length=1)
    old_path: str | None = None

    @field_validator("index_status", "worktree_status")
    @classmethod
    def _validate_status_character(cls, value: str) -> str:
        if value not in " MADRCUT?!":
            raise ValueError("unsupported porcelain status character")
        return value


class DiffSnapshot(StrictModel):
    """Immutable-ref provenance and canonical reviewer-visible diff input."""

    repo_root: Path
    base_ref: str
    head_ref: str | None
    base_sha: str
    head_sha: str
    merge_base_sha: str | None
    provenance: Literal["verified", "standalone"]
    comparison: Literal["committed", "working_tree"]
    include_untracked: bool
    changed_files: tuple[ChangedFile, ...]
    working_tree_status: tuple[WorkingTreeStatus, ...]
    patch: str
    diff_sha256: str

    @field_validator("base_sha", "head_sha", "merge_base_sha")
    @classmethod
    def _validate_git_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) not in {40, 64} or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("expected a full lowercase Git object ID")
        return value

    @field_validator("diff_sha256")
    @classmethod
    def _validate_diff_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("expected a lowercase SHA256 digest")
        return value

    @model_validator(mode="after")
    def _validate_snapshot_consistency(self) -> DiffSnapshot:
        if self.provenance == "verified" and self.merge_base_sha is not None:
            raise ValueError("verified snapshots cannot override the exact base with a merge base")
        if self.comparison == "working_tree" and self.head_ref is not None:
            raise ValueError("working-tree snapshots cannot have a user-supplied head ref")
        if self.comparison == "working_tree" and self.merge_base_sha is not None:
            raise ValueError("working-tree snapshots do not use merge-base comparison")
        if self.comparison == "committed" and self.working_tree_status:
            raise ValueError("committed snapshots cannot contain working-tree status")
        if (
            self.provenance == "standalone"
            and self.comparison == "committed"
            and self.merge_base_sha is None
        ):
            raise ValueError("standalone committed snapshots require a merge base")
        if _diff_hash(self.patch) != self.diff_sha256:
            raise ValueError("diff_sha256 does not match the canonical patch")
        return self


def _diff_hash(patch: str) -> str:
    return hashlib.sha256(patch.encode("utf-8", errors="surrogateescape")).hexdigest()


def _normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _decode_path(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape")


def parse_name_status_z(raw: bytes) -> tuple[ChangedFile, ...]:
    """Parse ``git diff --name-status -z`` without pathname delimiter ambiguity."""
    if not raw:
        return ()
    if not raw.endswith(b"\0"):
        raise DiffCaptureError("Git returned malformed NUL-delimited changed-file data")

    fields = raw[:-1].split(b"\0")
    changes: list[ChangedFile] = []
    index = 0
    while index < len(fields):
        token = fields[index]
        index += 1
        try:
            status_token = token.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise DiffCaptureError("Git returned an invalid changed-file status") from exc
        if not status_token:
            raise DiffCaptureError("Git returned an empty changed-file status")

        status = status_token[0]
        if status == "C":
            raise DiffCaptureError("Git unexpectedly reported copy detection")
        if status == "R":
            if len(status_token) == 1 or not status_token[1:].isdigit():
                raise DiffCaptureError("Git returned an invalid rename similarity")
            if index + 1 >= len(fields):
                raise DiffCaptureError("Git returned an incomplete rename record")
            old_path = _decode_path(fields[index])
            path = _decode_path(fields[index + 1])
            index += 2
            try:
                changes.append(
                    ChangedFile(
                        status="R",
                        path=path,
                        old_path=old_path,
                        similarity=int(status_token[1:]),
                    )
                )
            except ValueError as exc:
                raise DiffCaptureError("Git returned an invalid rename record") from exc
            continue

        if status_token not in {"A", "B", "D", "M", "T", "U", "X"}:
            raise DiffCaptureError("Git returned an unsupported changed-file status")
        if index >= len(fields):
            raise DiffCaptureError("Git returned an incomplete changed-file record")
        path = _decode_path(fields[index])
        index += 1
        try:
            changes.append(ChangedFile(status=status, path=path))  # type: ignore[arg-type]
        except ValueError as exc:
            raise DiffCaptureError("Git returned an invalid changed-file record") from exc
    return tuple(changes)


def _parse_working_tree_status_z(raw: bytes) -> tuple[WorkingTreeStatus, ...]:
    if not raw:
        return ()
    if not raw.endswith(b"\0"):
        raise DiffCaptureError("Git returned malformed working-tree status data")

    fields = raw[:-1].split(b"\0")
    statuses: list[WorkingTreeStatus] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if len(record) < 4 or record[2:3] != b" ":
            raise DiffCaptureError("Git returned malformed working-tree status data")
        try:
            index_status = record[0:1].decode("ascii", errors="strict")
            worktree_status = record[1:2].decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise DiffCaptureError("Git returned invalid working-tree status data") from exc
        path = _decode_path(record[3:])
        old_path: str | None = None
        if index_status in "RC" or worktree_status in "RC":
            if index >= len(fields):
                raise DiffCaptureError("Git returned incomplete working-tree rename data")
            old_path = _decode_path(fields[index])
            index += 1
        try:
            statuses.append(
                WorkingTreeStatus(
                    index_status=index_status,
                    worktree_status=worktree_status,
                    path=path,
                    old_path=old_path,
                )
            )
        except ValueError as exc:
            raise DiffCaptureError("Git returned invalid working-tree status data") from exc
    return tuple(statuses)


def _completed_git(
    repo: Path,
    *args: str,
    operation: str,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            shell=False,
        )
    except (OSError, ValueError) as exc:
        raise DiffCaptureError(f"Could not run Git while {operation}") from exc
    if completed.returncode not in allowed_returncodes:
        raise DiffCaptureError(f"Git failed while {operation}")
    return completed


def _git_bytes(repo: Path, *args: str, operation: str) -> bytes:
    return _completed_git(repo, *args, operation=operation).stdout


def _repository_root(repo: Path) -> Path:
    candidate = repo.expanduser()
    if not candidate.is_dir():
        raise DiffCaptureError("Repository path is not a Git repository")
    try:
        output = _git_bytes(
            candidate,
            "rev-parse",
            "--show-toplevel",
            operation="locating the repository root",
        )
        root = Path(output.decode("utf-8", errors="strict").strip()).resolve()
    except (DiffCaptureError, UnicodeDecodeError, OSError):
        raise DiffCaptureError("Repository path is not a Git repository") from None
    if not root.is_dir():
        raise DiffCaptureError("Repository path is not a Git repository")
    return root


def _resolve_commit(repo: Path, ref: str, *, label: Literal["base", "head"]) -> str:
    try:
        raw = _git_bytes(
            repo,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{ref}^{{commit}}",
            operation=f"resolving the {label} ref",
        )
        sha = raw.decode("ascii", errors="strict").strip().lower()
    except (DiffCaptureError, UnicodeDecodeError):
        raise DiffCaptureError(f"Could not resolve the {label} ref to a commit") from None
    if len(sha) not in {40, 64} or any(character not in "0123456789abcdef" for character in sha):
        raise DiffCaptureError(f"Could not resolve the {label} ref to a commit")
    return sha


def _require_ancestor(repo: Path, base_sha: str, head_sha: str) -> None:
    completed = _completed_git(
        repo,
        "merge-base",
        "--is-ancestor",
        base_sha,
        head_sha,
        operation="checking verified baseline ancestry",
        allowed_returncodes=(0, 1),
    )
    if completed.returncode == 1:
        raise DiffCaptureError("Verified base is not an ancestor of the implementation head")


def _merge_base(repo: Path, base_sha: str, head_sha: str) -> str:
    try:
        raw = _git_bytes(
            repo,
            "merge-base",
            base_sha,
            head_sha,
            operation="resolving the standalone merge base",
        )
        sha = raw.decode("ascii", errors="strict").strip().lower()
    except (DiffCaptureError, UnicodeDecodeError):
        raise DiffCaptureError("Could not resolve a merge base for the committed refs") from None
    if len(sha) not in {40, 64} or any(character not in "0123456789abcdef" for character in sha):
        raise DiffCaptureError("Could not resolve a merge base for the committed refs")
    return sha


def _diff_args(
    revisions: tuple[str, ...],
    *,
    context_lines: int,
    output: Literal["patch", "name-status", "raw", "numstat"],
) -> tuple[str, ...]:
    args: list[str] = [
        "-c",
        "core.quotePath=false",
        "-c",
        "core.bigFileThreshold=512m",
        "-c",
        "diff.suppressBlankEmpty=false",
        "-c",
        "diff.compactionHeuristic=false",
        "diff",
        *PATCH_FLAGS,
    ]
    if output == "patch":
        args.extend((f"--unified={context_lines}", "--inter-hunk-context=0"))
    elif output == "name-status":
        args.extend(("--name-status", "-z"))
    elif output == "raw":
        args.extend(("--raw", "-z"))
    elif output == "numstat":
        args.extend(("--numstat", "-z"))
    args.extend(revisions)
    args.append("--")
    return tuple(args)


def _parse_raw_kinds(raw: bytes) -> dict[str, FileKind]:
    if not raw:
        return {}
    if not raw.endswith(b"\0"):
        raise DiffCaptureError("Git returned malformed raw diff metadata")
    fields = raw[:-1].split(b"\0")
    kinds: dict[str, FileKind] = {}
    index = 0
    while index < len(fields):
        header = fields[index]
        index += 1
        parts = header.split()
        if len(parts) != 5 or not parts[0].startswith(b":"):
            raise DiffCaptureError("Git returned malformed raw diff metadata")
        status = parts[4][:1]
        if index >= len(fields):
            raise DiffCaptureError("Git returned incomplete raw diff metadata")
        path = _decode_path(fields[index])
        index += 1
        if status in {b"R", b"C"}:
            if index >= len(fields):
                raise DiffCaptureError("Git returned incomplete raw rename metadata")
            path = _decode_path(fields[index])
            index += 1
        modes = {parts[0][1:], parts[1]}
        if b"160000" in modes:
            kinds[path] = "submodule"
        elif b"120000" in modes:
            kinds[path] = "symlink"
    return kinds


def _parse_binary_paths(raw: bytes) -> set[str]:
    if not raw:
        return set()
    if not raw.endswith(b"\0"):
        raise DiffCaptureError("Git returned malformed binary diff metadata")
    fields = raw[:-1].split(b"\0")
    binary_paths: set[str] = set()
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        parts = record.split(b"\t", 2)
        if len(parts) != 3:
            raise DiffCaptureError("Git returned malformed binary diff metadata")
        added, deleted, path_bytes = parts
        is_binary = added == b"-" and deleted == b"-"
        if path_bytes:
            if is_binary:
                binary_paths.add(_decode_path(path_bytes))
            continue
        if index + 1 >= len(fields):
            raise DiffCaptureError("Git returned incomplete rename diff metadata")
        index += 1
        destination = _decode_path(fields[index])
        index += 1
        if is_binary:
            binary_paths.add(destination)
    return binary_paths


def _capture_tracked_component(
    repo: Path,
    revisions: tuple[str, ...],
    *,
    context_lines: int,
    source: Literal["committed", "staged", "unstaged", "working_tree"],
) -> tuple[str, tuple[ChangedFile, ...]]:
    patch = _git_bytes(
        repo,
        *_diff_args(revisions, context_lines=context_lines, output="patch"),
        operation=f"capturing {source} patch",
    ).decode("utf-8", errors="replace")
    names = _git_bytes(
        repo,
        *_diff_args(revisions, context_lines=context_lines, output="name-status"),
        operation=f"capturing {source} changed files",
    )
    raw = _git_bytes(
        repo,
        *_diff_args(revisions, context_lines=context_lines, output="raw"),
        operation=f"capturing {source} file modes",
    )
    numstat = _git_bytes(
        repo,
        *_diff_args(revisions, context_lines=context_lines, output="numstat"),
        operation=f"capturing {source} binary metadata",
    )

    mode_kinds = _parse_raw_kinds(raw)
    binary_paths = _parse_binary_paths(numstat)
    changes = []
    for change in parse_name_status_z(names):
        kind = mode_kinds.get(change.path)
        if kind is None:
            kind = "binary" if change.path in binary_paths else "text"
        changes.append(change.model_copy(update={"source": source, "kind": kind}))
    return _normalize_text(patch), tuple(changes)


def _safe_relative_path(path: str) -> PurePosixPath:
    pure = PurePosixPath(path)
    if (
        not path
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or PureWindowsPath(path).drive
    ):
        raise DiffCaptureError("Git returned an unsafe untracked path")
    return pure


def _metadata_section(path: str, kind: FileKind, size: int | None = None) -> str:
    suffix = "" if size is None else f"; bytes={size}"
    return (
        f"diff --krystal-quorum-untracked {json.dumps(path, ensure_ascii=False)}\n"
        f"metadata: content omitted; kind={kind}{suffix}\n"
    )


def _text_section(path: str, text: str) -> str:
    quoted_path = json.dumps(path, ensure_ascii=False)
    normalized = _normalize_text(text)
    header = (
        f"diff --krystal-quorum-untracked {quoted_path}\n"
        "new file mode 100644\n"
        "metadata: kind=text\n"
        "--- /dev/null\n"
        f"+++ {quoted_path}\n"
    )
    if not normalized:
        return header
    lines = normalized.split("\n")
    has_final_newline = normalized.endswith("\n")
    if has_final_newline:
        lines = lines[:-1]
    body = "".join(f"+{line}\n" for line in lines)
    if normalized and not has_final_newline:
        body += "\\ No newline at end of file\n"
    return header + f"@@ -0,0 +1,{len(lines)} @@\n{body}"


def _file_kind(info: os.stat_result) -> FileKind | None:
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(info.st_mode) or (reparse_flag and attributes & reparse_flag):
        return "symlink"
    if stat.S_ISFIFO(info.st_mode):
        return "fifo"
    if not stat.S_ISREG(info.st_mode):
        return "nonregular"
    if info.st_mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH) == 0:
        return "unreadable"
    return None


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        stat.S_IFMT(left.st_mode),
    ) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
    )


def _metadata_from_open_error(
    name: str,
    *,
    dir_fd: int,
) -> tuple[None, os.stat_result | None, FileKind]:
    try:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return None, None, "unreadable"
    return None, info, _file_kind(info) or "unreadable"


def _open_posix_untracked(
    repo: Path,
    pure: PurePosixPath,
) -> tuple[int | None, os.stat_result | None, FileKind | None]:
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
    )
    opened_directories: list[int] = []
    descriptor: int | None = None
    try:
        parent_fd = os.open(repo, directory_flags)
        opened_directories.append(parent_fd)
        for part in pure.parts[:-1]:
            try:
                parent_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            except OSError:
                return _metadata_from_open_error(part, dir_fd=opened_directories[-1])
            opened_directories.append(parent_fd)

        final_name = pure.parts[-1]
        try:
            descriptor = os.open(final_name, file_flags, dir_fd=parent_fd)
        except OSError:
            return _metadata_from_open_error(final_name, dir_fd=parent_fd)
        info = os.fstat(descriptor)
        try:
            post_open = os.stat(final_name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            raise DiffCaptureError("Untracked path changed during capture; retry") from None
        if not _same_file_identity(info, post_open):
            raise DiffCaptureError("Untracked path changed during capture; retry")
        return descriptor, info, None
    except DiffCaptureError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    finally:
        for directory_fd in reversed(opened_directories):
            os.close(directory_fd)


def _windows_final_path(descriptor: int) -> Path:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    handle = msvcrt.get_osfhandle(descriptor)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel32.GetFinalPathNameByHandleW
    function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    function.restype = wintypes.DWORD
    required = function(handle, None, 0, 0)
    if required == 0:
        raise OSError(ctypes.get_last_error(), "Could not resolve opened file path")
    buffer = ctypes.create_unicode_buffer(required + 1)
    written = function(handle, buffer, len(buffer), 0)
    if written == 0 or written >= len(buffer):
        raise OSError(ctypes.get_last_error(), "Could not resolve opened file path")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _path_is_within(path: Path, parent: Path) -> bool:
    path_value = os.path.normcase(os.path.abspath(path))
    parent_value = os.path.normcase(os.path.abspath(parent))
    try:
        return os.path.commonpath((path_value, parent_value)) == parent_value
    except ValueError:
        return False


def _open_windows_untracked(
    repo: Path,
    pure: PurePosixPath,
) -> tuple[int | None, os.stat_result | None, FileKind | None]:
    candidate = repo
    baseline: os.stat_result | None = None
    try:
        for index, part in enumerate(pure.parts):
            candidate = candidate / part
            baseline = candidate.lstat()
            kind = _file_kind(baseline)
            if kind is not None:
                return None, baseline, kind
            if index < len(pure.parts) - 1 and not stat.S_ISDIR(baseline.st_mode):
                return None, baseline, "nonregular"
    except OSError:
        return None, baseline, "unreadable"

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(candidate, flags)
        opened = os.fstat(descriptor)
        if baseline is None or not _same_file_identity(baseline, opened):
            raise DiffCaptureError("Untracked path changed during capture; retry")
        if not stat.S_ISREG(opened.st_mode):
            raise DiffCaptureError("Untracked path changed during capture; retry")
        final_path = _windows_final_path(descriptor)
        if not _path_is_within(final_path, repo):
            raise DiffCaptureError("Untracked descriptor resolved outside repository")
        try:
            post_open = candidate.lstat()
        except OSError:
            raise DiffCaptureError("Untracked path changed during capture; retry") from None
        if not _same_file_identity(opened, post_open):
            raise DiffCaptureError("Untracked path changed during capture; retry")
        return descriptor, opened, None
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        return None, baseline, "unreadable"
    except DiffCaptureError:
        if descriptor is not None:
            os.close(descriptor)
        raise


def _open_untracked_descriptor(
    repo: Path,
    pure: PurePosixPath,
) -> tuple[int | None, os.stat_result | None, FileKind | None]:
    if os.name == "nt":
        return _open_windows_untracked(repo, pure)
    return _open_posix_untracked(repo, pure)


def _read_descriptor_bytes(descriptor: int, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(READ_CHUNK_BYTES, remaining))
        if not chunk:
            return b"".join(chunks), True
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks), False


def _read_untracked(
    repo: Path,
    path: str,
    *,
    max_diff_chars: int,
) -> tuple[str, FileKind]:
    pure = _safe_relative_path(path)
    descriptor, info, omitted_kind = _open_untracked_descriptor(repo, pure)
    if descriptor is None:
        size = None if info is None else info.st_size
        kind = omitted_kind or "unreadable"
        return _metadata_section(path, kind, size), kind

    try:
        if info is None:
            raise DiffCaptureError("Untracked path changed during capture; retry")
        kind = _file_kind(info)
        if kind is not None:
            return _metadata_section(path, kind, info.st_size), kind
        max_bytes = max(DEFAULT_MAX_DIFF_CHARS, max_diff_chars) * 4 + 4
        content, complete = _read_descriptor_bytes(descriptor, max_bytes)
    finally:
        os.close(descriptor)

    if b"\0" in content:
        return _metadata_section(path, "binary", info.st_size), "binary"
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        if complete or exc.end < len(content) or exc.reason != "unexpected end of data":
            return _metadata_section(path, "binary", info.st_size), "binary"
        text = ""
    if not complete:
        rough_tokens = (max_diff_chars + 3) // 4
        raise DiffCaptureError(
            "Untracked text exceeds safe read bound: "
            f"actual_bytes={info.st_size}; limit_chars={max_diff_chars}; "
            f"rough_tokens_at_least={rough_tokens}"
        )
    return _text_section(path, text), "text"


def _capture_untracked(
    repo: Path,
    *,
    include_content: bool,
    max_diff_chars: int,
) -> tuple[bytes, str, tuple[ChangedFile, ...]]:
    raw = _git_bytes(
        repo,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        operation="listing eligible untracked files",
    )
    if not raw:
        return b"", "", ()
    if not raw.endswith(b"\0"):
        raise DiffCaptureError("Git returned malformed untracked-file data")
    if not include_content:
        return raw, "", ()

    sections: list[str] = []
    changes: list[ChangedFile] = []
    for path_bytes in sorted(raw[:-1].split(b"\0")):
        path = _decode_path(path_bytes)
        section, kind = _read_untracked(repo, path, max_diff_chars=max_diff_chars)
        sections.append(section.rstrip("\n"))
        changes.append(ChangedFile(status="A", path=path, source="untracked", kind=kind))
    return raw, "\n\n".join(sections) + "\n", tuple(changes)


@dataclass(frozen=True)
class _MutableState:
    head_sha: str
    index_tree: bytes
    status_raw: bytes
    working_tree_status: tuple[WorkingTreeStatus, ...]
    committed_patch: str
    committed_changes: tuple[ChangedFile, ...]
    staged_patch: str
    staged_changes: tuple[ChangedFile, ...]
    unstaged_patch: str
    unstaged_changes: tuple[ChangedFile, ...]
    untracked_raw: bytes
    untracked_patch: str
    untracked_changes: tuple[ChangedFile, ...]


def _working_tree_status_bytes(repo: Path) -> bytes:
    return _git_bytes(
        repo,
        "-c",
        "core.quotePath=false",
        "-c",
        "status.renames=true",
        "-c",
        "status.renameLimit=1000",
        "-c",
        "diff.renameLimit=1000",
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
        "--find-renames=50%",
        "--",
        operation="capturing working-tree status",
    )


def _capture_mutable_state(
    repo: Path,
    *,
    base_sha: str,
    include_untracked: bool,
    max_diff_chars: int,
    context_lines: int,
) -> _MutableState:
    head_before = _resolve_commit(repo, "HEAD", label="head")
    index_tree = _git_bytes(repo, "write-tree", operation="capturing index state").strip()
    status_raw = _working_tree_status_bytes(repo)
    committed_patch, committed_changes = _capture_tracked_component(
        repo,
        (base_sha, head_before),
        context_lines=context_lines,
        source="committed",
    )
    staged_patch, staged_changes = _capture_tracked_component(
        repo,
        ("--cached", head_before),
        context_lines=context_lines,
        source="staged",
    )
    unstaged_patch, unstaged_changes = _capture_tracked_component(
        repo,
        (),
        context_lines=context_lines,
        source="unstaged",
    )
    untracked_raw, untracked_patch, untracked_changes = _capture_untracked(
        repo,
        include_content=include_untracked,
        max_diff_chars=max_diff_chars,
    )
    head_after = _resolve_commit(repo, "HEAD", label="head")
    if head_before != head_after:
        raise DiffCaptureError("Repository changed during diff capture; retry")
    return _MutableState(
        head_sha=head_before,
        index_tree=index_tree,
        status_raw=status_raw,
        working_tree_status=_parse_working_tree_status_z(status_raw),
        committed_patch=committed_patch,
        committed_changes=committed_changes,
        staged_patch=staged_patch,
        staged_changes=staged_changes,
        unstaged_patch=unstaged_patch,
        unstaged_changes=unstaged_changes,
        untracked_raw=untracked_raw,
        untracked_patch=untracked_patch,
        untracked_changes=untracked_changes,
    )


def _canonical_changed_files(
    *groups: tuple[ChangedFile, ...],
    mutable: bool = False,
) -> tuple[ChangedFile, ...]:
    changes = [
        change.model_copy(update={"source": "working_tree"})
        if mutable and change.source != "untracked"
        else change
        for group in groups
        for change in group
    ]
    by_path: dict[str, ChangedFile] = {}
    for change in changes:
        existing = by_path.get(change.path)
        if existing is None:
            by_path[change.path] = change
            continue
        statuses = {existing.status, change.status}
        rename = existing if existing.status == "R" else change if change.status == "R" else None
        if len(statuses) == 1:
            status = existing.status
        elif statuses == {"A", "D"}:
            status = "M"
        elif rename is not None:
            status = "R"
        elif "D" in statuses:
            status = "D"
        elif "A" in statuses:
            status = "A"
        elif "T" in statuses:
            status = "T"
        else:
            status = "M"
        kind_order: dict[FileKind | None, int] = {
            None: 0,
            "text": 1,
            "binary": 2,
            "symlink": 3,
            "submodule": 4,
            "unreadable": 5,
            "fifo": 6,
            "nonregular": 7,
        }
        kind = max((existing.kind, change.kind), key=kind_order.__getitem__)
        source: ChangeSource = (
            "untracked"
            if existing.source == change.source == "untracked"
            else "working_tree"
        )
        by_path[change.path] = ChangedFile(
            status=status,
            path=change.path,
            old_path=None if rename is None else rename.old_path,
            similarity=None if rename is None else rename.similarity,
            source=source,
            kind=kind,
        )
    return tuple(
        sorted(
            by_path.values(),
            key=lambda change: (change.path, change.old_path or "", change.status),
        )
    )


def _labeled_section(label: str, patch: str) -> str:
    normalized = _normalize_text(patch)
    if not normalized:
        return ""
    normalized = normalized.rstrip("\n")
    return f"### krystal-quorum diff: {label}\n{normalized}\n"


def _validate_bounds(max_diff_chars: int, context_lines: int) -> None:
    if isinstance(max_diff_chars, bool) or not isinstance(max_diff_chars, int) or max_diff_chars <= 0:
        raise DiffCaptureError("max_diff_chars must be a positive integer")
    if (
        isinstance(context_lines, bool)
        or not isinstance(context_lines, int)
        or not 0 <= context_lines <= 200
    ):
        raise DiffCaptureError("context_lines must be an integer from 0 to 200")


def capture_diff(
    repo: Path,
    *,
    base_ref: str,
    head_ref: str | None = None,
    verified_base: bool = False,
    include_untracked: bool = True,
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS,
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> DiffSnapshot:
    """Capture one deterministic committed or working-tree Git snapshot."""
    _validate_bounds(max_diff_chars, context_lines)
    repo_root = _repository_root(Path(repo))
    base_sha = _resolve_commit(repo_root, base_ref, label="base")
    head_sha = _resolve_commit(repo_root, head_ref if head_ref is not None else "HEAD", label="head")

    provenance: Literal["verified", "standalone"] = (
        "verified" if verified_base else "standalone"
    )
    comparison: Literal["committed", "working_tree"] = (
        "committed" if head_ref is not None else "working_tree"
    )
    merge_base_sha: str | None = None
    if verified_base:
        _require_ancestor(repo_root, base_sha, head_sha)
    elif comparison == "committed":
        merge_base_sha = _merge_base(repo_root, base_sha, head_sha)

    sections: list[str] = []
    changed_files: tuple[ChangedFile, ...]
    working_tree_status: tuple[WorkingTreeStatus, ...] = ()
    if comparison == "committed":
        revisions = (
            (base_sha, head_sha)
            if verified_base
            else (f"{base_sha}...{head_sha}",)
        )
        patch, changes = _capture_tracked_component(
            repo_root,
            revisions,
            context_lines=context_lines,
            source="committed",
        )
        if patch:
            sections.append(_labeled_section("committed", patch))
        changed_files = _canonical_changed_files(changes)
    else:
        first = _capture_mutable_state(
            repo_root,
            base_sha=base_sha,
            include_untracked=include_untracked,
            max_diff_chars=max_diff_chars,
            context_lines=context_lines,
        )
        second = _capture_mutable_state(
            repo_root,
            base_sha=base_sha,
            include_untracked=include_untracked,
            max_diff_chars=max_diff_chars,
            context_lines=context_lines,
        )
        if first != second or first.head_sha != head_sha:
            raise DiffCaptureError("Repository changed during diff capture; retry")
        if first.committed_patch:
            sections.append(_labeled_section("committed", first.committed_patch))
        if first.staged_patch:
            sections.append(_labeled_section("staged", first.staged_patch))
        if first.unstaged_patch:
            sections.append(_labeled_section("unstaged", first.unstaged_patch))
        if first.untracked_patch:
            sections.append(_labeled_section("untracked", first.untracked_patch))
        changed_files = _canonical_changed_files(
            first.committed_changes,
            first.staged_changes,
            first.unstaged_changes,
            first.untracked_changes,
            mutable=True,
        )
        working_tree_status = first.working_tree_status

    patch = _normalize_text("\n".join(section.rstrip("\n") for section in sections))
    if patch:
        patch += "\n"
    actual_chars = len(patch)
    if actual_chars > max_diff_chars:
        rough_tokens = (actual_chars + 3) // 4
        raise DiffCaptureError(
            "Diff exceeds max_diff_chars: "
            f"actual_chars={actual_chars}; limit={max_diff_chars}; rough_tokens={rough_tokens}"
        )

    return DiffSnapshot(
        repo_root=repo_root,
        base_ref=base_ref,
        head_ref=head_ref,
        base_sha=base_sha,
        head_sha=head_sha,
        merge_base_sha=merge_base_sha,
        provenance=provenance,
        comparison=comparison,
        include_untracked=include_untracked,
        changed_files=changed_files,
        working_tree_status=working_tree_status,
        patch=patch,
        diff_sha256=_diff_hash(patch),
    )
