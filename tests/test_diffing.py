from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess

from pydantic import ValidationError
import pytest

import krystal_quorum.diffing as diffing
from krystal_quorum.diffing import (
    ChangedFile,
    DiffCaptureError,
    DiffSnapshot,
    capture_diff,
    parse_name_status_z,
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        shell=False,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(tmp_path: Path, name: str = "repo") -> tuple[Path, str]:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Tests")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _by_path(snapshot: DiffSnapshot) -> dict[str, ChangedFile]:
    return {item.path: item for item in snapshot.changed_files}


def test_parse_name_status_z_is_nul_safe_and_preserves_rename_paths() -> None:
    raw = (
        b"M\0space name.txt\0"
        b"A\0tab\tname.txt\0"
        b"D\0line\nname.txt\0"
        b"R087\0old \xe2\x98\x83.txt\0new\t\xe9\x9b\xaa.txt\0"
    )

    changes = parse_name_status_z(raw)

    assert [item.model_dump(mode="json") for item in changes] == [
        {
            "status": "M",
            "path": "space name.txt",
            "old_path": None,
            "similarity": None,
            "source": "tracked",
            "kind": None,
        },
        {
            "status": "A",
            "path": "tab\tname.txt",
            "old_path": None,
            "similarity": None,
            "source": "tracked",
            "kind": None,
        },
        {
            "status": "D",
            "path": "line\nname.txt",
            "old_path": None,
            "similarity": None,
            "source": "tracked",
            "kind": None,
        },
        {
            "status": "R",
            "path": "new\t\N{CJK UNIFIED IDEOGRAPH-96EA}.txt",
            "old_path": "old \N{SNOWMAN}.txt",
            "similarity": 87,
            "source": "tracked",
            "kind": None,
        },
    ]


@pytest.mark.parametrize(
    "raw",
    [
        b"M\0missing-terminator",
        b"R100\0only-old.txt\0",
        b"Q\0unknown.txt\0",
        b"C100\0source.txt\0copy.txt\0",
    ],
)
def test_parse_name_status_z_rejects_malformed_or_copy_records(raw: bytes) -> None:
    with pytest.raises(DiffCaptureError):
        parse_name_status_z(raw)


def test_changed_file_and_snapshot_are_strict_models() -> None:
    with pytest.raises(ValidationError):
        ChangedFile(status="R", path="new.txt")
    with pytest.raises(ValidationError):
        ChangedFile(status="A", path="new.txt", unexpected=True)
    with pytest.raises(ValidationError):
        DiffSnapshot(
            repo_root=Path("."),
            base_ref="main",
            head_ref="HEAD",
            base_sha="a" * 40,
            head_sha="b" * 40,
            merge_base_sha=None,
            provenance="standalone",
            comparison="committed",
            include_untracked=False,
            changed_files=(),
            working_tree_status=(),
            patch="",
            diff_sha256=hashlib.sha256(b"").hexdigest(),
            unexpected=True,
        )


def test_verified_committed_capture_resolves_refs_and_uses_exact_base(tmp_path: Path) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "base.txt").write_text("base\nverified change\n", encoding="utf-8")
    head_sha = _commit_all(repo, "implementation")

    snapshot = capture_diff(
        repo,
        base_ref=base_sha,
        head_ref="HEAD",
        verified_base=True,
    )

    assert snapshot.repo_root == repo.resolve()
    assert snapshot.base_ref == base_sha
    assert snapshot.head_ref == "HEAD"
    assert snapshot.base_sha == base_sha
    assert snapshot.head_sha == head_sha
    assert snapshot.merge_base_sha is None
    assert snapshot.provenance == "verified"
    assert snapshot.comparison == "committed"
    assert "verified change" in snapshot.patch
    assert [(item.status, item.path, item.source) for item in snapshot.changed_files] == [
        ("M", "base.txt", "committed")
    ]


def test_verified_capture_rejects_a_non_ancestor_without_merge_base_override(
    tmp_path: Path,
) -> None:
    repo, root_sha = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "approved")
    (repo / "approved.txt").write_text("approved branch\n", encoding="utf-8")
    approved_sha = _commit_all(repo, "approved branch")
    _git(repo, "checkout", "--detach", root_sha)
    (repo / "implementation.txt").write_text("other history\n", encoding="utf-8")
    implementation_sha = _commit_all(repo, "other history")

    with pytest.raises(DiffCaptureError, match="not an ancestor"):
        capture_diff(
            repo,
            base_ref=approved_sha,
            head_ref=implementation_sha,
            verified_base=True,
        )


def test_standalone_committed_capture_uses_three_dot_merge_base_semantics(
    tmp_path: Path,
) -> None:
    repo, root_sha = _init_repo(tmp_path)
    main_branch = _git(repo, "branch", "--show-current")
    _git(repo, "checkout", "-b", "feature")
    (repo / "feature.txt").write_text("feature only\n", encoding="utf-8")
    feature_sha = _commit_all(repo, "feature")
    _git(repo, "checkout", main_branch)
    (repo / "main.txt").write_text("main only\n", encoding="utf-8")
    main_sha = _commit_all(repo, "main")

    snapshot = capture_diff(repo, base_ref=main_sha, head_ref=feature_sha)

    assert snapshot.base_sha == main_sha
    assert snapshot.head_sha == feature_sha
    assert snapshot.merge_base_sha == root_sha
    assert snapshot.provenance == "standalone"
    assert snapshot.comparison == "committed"
    assert "feature only" in snapshot.patch
    assert "main only" not in snapshot.patch
    assert [(item.status, item.path) for item in snapshot.changed_files] == [
        ("A", "feature.txt")
    ]


def test_working_tree_capture_combines_committed_staged_unstaged_and_untracked(
    tmp_path: Path,
) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "committed.txt").write_text("committed layer\n", encoding="utf-8")
    _commit_all(repo, "committed layer")

    (repo / "both.txt").write_text("staged version\n", encoding="utf-8")
    (repo / "staged.txt").write_text("staged layer\n", encoding="utf-8")
    _git(repo, "add", "both.txt", "staged.txt")
    (repo / "both.txt").write_text("staged version\nunstaged version\n", encoding="utf-8")
    (repo / "base.txt").write_text("base\nunstaged layer\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked layer\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repo / "ignored.txt").write_text("must stay out\n", encoding="utf-8")

    snapshot = capture_diff(repo, base_ref=base_sha, include_untracked=True)

    assert snapshot.comparison == "working_tree"
    assert snapshot.head_ref is None
    assert snapshot.merge_base_sha is None
    assert "committed layer" in snapshot.patch
    assert "staged layer" in snapshot.patch
    assert "unstaged layer" in snapshot.patch
    assert "unstaged version" in snapshot.patch
    assert "untracked layer" in snapshot.patch
    assert "must stay out" not in snapshot.patch
    assert "krystal-quorum diff: committed" in snapshot.patch
    assert "krystal-quorum diff: staged" in snapshot.patch
    assert "krystal-quorum diff: unstaged" in snapshot.patch
    assert "krystal-quorum diff: untracked" in snapshot.patch
    sources = [(item.path, item.source) for item in snapshot.changed_files]
    assert ("committed.txt", "working_tree") in sources
    assert ("staged.txt", "working_tree") in sources
    assert ("both.txt", "working_tree") in sources
    assert sources.count(("both.txt", "working_tree")) == 1
    assert ("base.txt", "working_tree") in sources
    assert ("untracked.txt", "untracked") in sources
    assert all(item.path != "ignored.txt" for item in snapshot.changed_files)
    status_by_path = {item.path: item for item in snapshot.working_tree_status}
    assert status_by_path["both.txt"].index_status == "A"
    assert status_by_path["both.txt"].worktree_status == "M"
    assert status_by_path["staged.txt"].index_status == "A"
    assert status_by_path["staged.txt"].worktree_status == " "
    assert status_by_path["base.txt"].index_status == " "
    assert status_by_path["base.txt"].worktree_status == "M"
    assert status_by_path["untracked.txt"].index_status == "?"
    assert status_by_path["untracked.txt"].worktree_status == "?"


def test_mm_status_preserves_staged_evidence_and_unstaged_reversal_once(
    tmp_path: Path,
) -> None:
    repo, _ = _init_repo(tmp_path)
    layered = repo / "layered.txt"
    layered.write_text("original head bytes\n", encoding="utf-8")
    base_sha = _commit_all(repo, "layered base")
    layered.write_text("staged evidence bytes\n", encoding="utf-8")
    _git(repo, "add", "layered.txt")
    layered.write_text("original head bytes\n", encoding="utf-8")

    snapshot = capture_diff(repo, base_ref=base_sha, include_untracked=False)
    staged_start = snapshot.patch.index("### krystal-quorum diff: staged")
    unstaged_start = snapshot.patch.index("### krystal-quorum diff: unstaged")
    staged_section = snapshot.patch[staged_start:unstaged_start]
    unstaged_section = snapshot.patch[unstaged_start:]
    matches = [item for item in snapshot.changed_files if item.path == "layered.txt"]

    assert "+staged evidence bytes" in staged_section
    assert "-staged evidence bytes" in unstaged_section
    assert "+original head bytes" in unstaged_section
    assert len(matches) == 1
    assert matches[0].status == "M"
    assert matches[0].source == "working_tree"
    status = next(item for item in snapshot.working_tree_status if item.path == "layered.txt")
    assert status.index_status == "M"
    assert status.worktree_status == "M"


def test_working_tree_can_exclude_untracked_files(tmp_path: Path) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "untracked.txt").write_text("not requested\n", encoding="utf-8")

    snapshot = capture_diff(repo, base_ref=base_sha, include_untracked=False)

    assert snapshot.patch == ""
    assert snapshot.changed_files == ()
    assert [(item.index_status, item.worktree_status, item.path) for item in snapshot.working_tree_status] == [
        ("?", "?", "untracked.txt")
    ]


def test_canonical_union_treats_staged_delete_plus_untracked_recreation_as_modified(
    tmp_path: Path,
) -> None:
    repo, _ = _init_repo(tmp_path)
    (repo / "recreated.txt").write_text("original tracked bytes\n", encoding="utf-8")
    base_sha = _commit_all(repo, "tracked path")
    _git(repo, "rm", "recreated.txt")
    (repo / "recreated.txt").write_text("replacement untracked bytes\n", encoding="utf-8")

    snapshot = capture_diff(repo, base_ref=base_sha, include_untracked=True)
    matches = [item for item in snapshot.changed_files if item.path == "recreated.txt"]

    assert len(matches) == 1
    assert matches[0].status == "M"
    assert matches[0].source == "working_tree"
    assert matches[0].kind == "text"
    assert "replacement untracked bytes" in snapshot.patch


@pytest.mark.parametrize("mutation", ["head", "index", "worktree", "untracked"])
def test_mutable_capture_rejects_any_change_between_complete_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "base.txt").write_text("base\ninitial worktree\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("initial untracked\n", encoding="utf-8")
    original_capture = diffing._capture_mutable_state
    captures = 0

    def mutating_capture(*args: object, **kwargs: object) -> object:
        nonlocal captures
        state = original_capture(*args, **kwargs)
        captures += 1
        if captures != 1:
            return state
        if mutation == "head":
            (repo / "head-change.txt").write_text("new head\n", encoding="utf-8")
            _commit_all(repo, "concurrent head")
        elif mutation == "index":
            (repo / "index-change.txt").write_text("new index\n", encoding="utf-8")
            _git(repo, "add", "index-change.txt")
        elif mutation == "worktree":
            (repo / "base.txt").write_text("base\nchanged again\n", encoding="utf-8")
        else:
            (repo / "untracked.txt").write_text("changed untracked\n", encoding="utf-8")
        return state

    monkeypatch.setattr(diffing, "_capture_mutable_state", mutating_capture)

    with pytest.raises(DiffCaptureError, match="changed during diff capture; retry"):
        capture_diff(repo, base_ref=base_sha)


def test_committed_capture_reports_add_delete_rename_and_copy_as_add(tmp_path: Path) -> None:
    repo, _ = _init_repo(tmp_path)
    (repo / "delete.txt").write_text("delete this unique line\n", encoding="utf-8")
    (repo / "rename-source.txt").write_text("rename this exact content\n", encoding="utf-8")
    (repo / "copy-source.txt").write_text("copy remains at source\n", encoding="utf-8")
    base_sha = _commit_all(repo, "fixtures")

    (repo / "delete.txt").unlink()
    (repo / "rename-source.txt").rename(repo / "rename-destination.txt")
    shutil.copyfile(repo / "copy-source.txt", repo / "copy-destination.txt")
    (repo / "added.txt").write_text("brand new unique line\n", encoding="utf-8")
    head_sha = _commit_all(repo, "changes")

    snapshot = capture_diff(repo, base_ref=base_sha, head_ref=head_sha)
    changes = _by_path(snapshot)

    assert changes["delete.txt"].status == "D"
    assert changes["rename-destination.txt"].status == "R"
    assert changes["rename-destination.txt"].old_path == "rename-source.txt"
    assert changes["copy-destination.txt"].status == "A"
    assert changes["copy-destination.txt"].old_path is None
    assert changes["added.txt"].status == "A"


def test_capture_preserves_unusual_paths_from_real_git_output(tmp_path: Path) -> None:
    repo, base_sha = _init_repo(tmp_path)
    paths = ["space name.txt", "tab\tname.txt", "line\nname.txt", "caf\N{LATIN SMALL LETTER E WITH ACUTE}.txt"]
    try:
        for name in paths:
            (repo / name).write_text(f"content for {name}\n", encoding="utf-8")
    except OSError as exc:
        pytest.skip(f"filesystem rejects tab or newline paths: {exc}")
    head_sha = _commit_all(repo, "unusual paths")

    snapshot = capture_diff(repo, base_ref=base_sha, head_ref=head_sha)

    assert {item.path for item in snapshot.changed_files} == set(paths)


def test_empty_diff_has_empty_patch_and_deterministic_hash(tmp_path: Path) -> None:
    repo, head_sha = _init_repo(tmp_path)

    first = capture_diff(repo, base_ref=head_sha, head_ref=head_sha)
    second = capture_diff(repo, base_ref=head_sha, head_ref=head_sha)

    assert first.patch == ""
    assert first.changed_files == ()
    assert first.diff_sha256 == hashlib.sha256(b"").hexdigest()
    assert first == second


def test_tracked_patch_preserves_meaningful_trailing_spaces(tmp_path: Path) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "base.txt").write_bytes(b"base\nline with spaces  \n")
    head_sha = _commit_all(repo, "trailing spaces")

    snapshot = capture_diff(repo, base_ref=base_sha, head_ref=head_sha)

    assert "+line with spaces  \n" in snapshot.patch


def test_tracked_binary_and_untracked_text_and_binary_have_metadata(
    tmp_path: Path,
) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "tracked.bin").write_bytes(b"before\0binary")
    _commit_all(repo, "binary base")
    binary_base = _git(repo, "rev-parse", "HEAD")
    (repo / "tracked.bin").write_bytes(b"after\0binary")
    _commit_all(repo, "binary changed")
    (repo / "notes.txt").write_bytes(b"first\r\nsecond\rthird\n")
    (repo / "untracked.bin").write_bytes(b"\x00\xff\x01")

    snapshot = capture_diff(repo, base_ref=binary_base, include_untracked=True)
    changes = _by_path(snapshot)

    assert base_sha != binary_base
    assert changes["tracked.bin"].kind == "binary"
    assert changes["notes.txt"].kind == "text"
    assert changes["untracked.bin"].kind == "binary"
    assert "Binary files" in snapshot.patch
    assert "first\n+second\n+third" in snapshot.patch
    assert "content omitted; kind=binary" in snapshot.patch
    assert "\r" not in snapshot.patch
    assert snapshot.diff_sha256 == hashlib.sha256(snapshot.patch.encode("utf-8")).hexdigest()


def test_empty_untracked_text_has_new_file_metadata_without_a_fake_hunk(
    tmp_path: Path,
) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "empty.txt").write_bytes(b"")

    snapshot = capture_diff(repo, base_ref=base_sha, include_untracked=True)

    assert _by_path(snapshot)["empty.txt"].kind == "text"
    assert "new file mode 100644" in snapshot.patch
    assert 'metadata: kind=text\n--- /dev/null\n+++ "empty.txt"\n' in snapshot.patch
    assert "@@ -0,0" not in snapshot.patch
    assert "\n+\n" not in snapshot.patch


def test_untracked_symlink_is_never_followed(tmp_path: Path) -> None:
    repo, base_sha = _init_repo(tmp_path)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("never expose this target\n", encoding="utf-8")
    link = repo / "outside-link"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    snapshot = capture_diff(repo, base_ref=base_sha, include_untracked=True)
    change = _by_path(snapshot)["outside-link"]

    assert change.kind == "symlink"
    assert "content omitted; kind=symlink" in snapshot.patch
    assert "never expose this target" not in snapshot.patch


def test_untracked_reader_rejects_an_injected_replacement_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = _init_repo(tmp_path)
    victim = repo / "victim.txt"
    outside = tmp_path / "outside-secret.txt"
    victim.write_text("expected bytes\n", encoding="utf-8")
    outside.write_text("outside secret\n", encoding="utf-8")
    original_open = diffing.os.open

    def swapped_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        path_value = os.fspath(path)
        is_victim = (
            path_value == victim.name if dir_fd is not None else Path(path_value) == victim
        )
        if is_victim:
            return original_open(
                outside,
                os.O_RDONLY | getattr(os, "O_BINARY", 0),
            )
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(diffing.os, "open", swapped_open)

    with pytest.raises(DiffCaptureError, match="changed during capture"):
        diffing._read_untracked(repo, "victim.txt", max_diff_chars=160_000)


def test_untracked_reader_uses_bounded_descriptor_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "bounded.txt").write_text("bounded descriptor bytes\n", encoding="utf-8")
    original_read = diffing.os.read
    requested_sizes: list[int] = []

    def recording_read(descriptor: int, size: int) -> bytes:
        requested_sizes.append(size)
        return original_read(descriptor, size)

    monkeypatch.setattr(diffing.os, "read", recording_read)

    snapshot = capture_diff(repo, base_ref=base_sha, max_diff_chars=2000)

    assert "bounded descriptor bytes" in snapshot.patch
    assert requested_sizes
    assert all(0 < size <= 64 * 1024 for size in requested_sizes)


def test_injected_out_of_root_untracked_path_fails_before_any_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _init_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside bytes\n", encoding="utf-8")
    original_git_bytes = diffing._git_bytes

    def injected_git_bytes(
        target_repo: Path,
        *args: str,
        operation: str,
    ) -> bytes:
        if args and args[0] == "ls-files":
            return b"../outside.txt\0"
        return original_git_bytes(target_repo, *args, operation=operation)

    def explode_read(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("unsafe paths must fail before descriptor reads")

    monkeypatch.setattr(diffing, "_git_bytes", injected_git_bytes)
    monkeypatch.setattr(diffing, "_read_descriptor_bytes", explode_read, raising=False)

    with pytest.raises(DiffCaptureError, match="unsafe untracked path"):
        capture_diff(repo, base_ref=base_sha)


@pytest.mark.skipif(os.name == "nt", reason="POSIX dir_fd traversal is required")
def test_posix_intermediate_symlink_is_not_traversed(tmp_path: Path) -> None:
    repo, _ = _init_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside secret\n", encoding="utf-8")
    (repo / "linked").symlink_to(outside, target_is_directory=True)

    section, kind = diffing._read_untracked(
        repo,
        "linked/secret.txt",
        max_diff_chars=160_000,
    )

    assert kind == "symlink"
    assert "content omitted; kind=symlink" in section
    assert "outside secret" not in section


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unsupported on this platform")
def test_untracked_fifo_is_opened_nonblocking_and_is_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _init_repo(tmp_path)
    fifo = repo / "events.pipe"
    os.mkfifo(fifo)
    original_open = diffing.os.open
    final_open_flags: list[int] = []

    def recording_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None and os.fspath(path) == fifo.name:
            final_open_flags.append(flags)
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(diffing.os, "open", recording_open)

    snapshot = capture_diff(repo, base_ref=base_sha, include_untracked=True)
    change = _by_path(snapshot)["events.pipe"]

    assert change.kind == "fifo"
    assert "content omitted; kind=fifo" in snapshot.patch
    assert final_open_flags
    assert all(flags & os.O_NONBLOCK for flags in final_open_flags)
    assert all(flags & os.O_NOFOLLOW for flags in final_open_flags)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are required")
def test_unreadable_untracked_file_is_metadata_only(tmp_path: Path) -> None:
    repo, base_sha = _init_repo(tmp_path)
    unreadable = repo / "unreadable.txt"
    unreadable.write_text("do not read\n", encoding="utf-8")
    unreadable.chmod(0)
    try:
        try:
            unreadable.read_bytes()
        except PermissionError:
            pass
        else:
            pytest.skip("current user can still read mode-000 files")

        snapshot = capture_diff(repo, base_ref=base_sha, include_untracked=True)
    finally:
        unreadable.chmod(stat.S_IRUSR | stat.S_IWUSR)

    change = _by_path(snapshot)["unreadable.txt"]
    assert change.kind == "unreadable"
    assert "content omitted; kind=unreadable" in snapshot.patch
    assert "do not read" not in snapshot.patch


def test_changed_submodule_is_classified_and_emits_git_metadata(tmp_path: Path) -> None:
    child, _ = _init_repo(tmp_path, "child")
    parent, _ = _init_repo(tmp_path, "parent")
    completed = subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(child),
            "vendor/child",
        ],
        cwd=parent,
        check=False,
        capture_output=True,
        shell=False,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip(f"local submodules unavailable: {completed.stderr.strip()}")
    base_sha = _commit_all(parent, "add submodule")

    (child / "child-change.txt").write_text("next child revision\n", encoding="utf-8")
    child_head = _commit_all(child, "child change")
    _git(parent / "vendor" / "child", "fetch")
    _git(parent / "vendor" / "child", "checkout", child_head)
    head_sha = _commit_all(parent, "advance submodule")

    snapshot = capture_diff(parent, base_ref=base_sha, head_ref=head_sha)
    change = _by_path(snapshot)["vendor/child"]

    assert change.kind == "submodule"
    assert "Subproject commit" in snapshot.patch


def test_local_diff_config_cannot_change_patch_hash_or_hide_dirty_submodule(
    tmp_path: Path,
) -> None:
    child, _ = _init_repo(tmp_path, "config-child")
    parent, _ = _init_repo(tmp_path, "config-parent")
    (parent / "alpha.txt").write_text("alpha base\n", encoding="utf-8")
    (parent / "zeta.txt").write_text("zeta base\n", encoding="utf-8")
    (parent / "copy-source.txt").write_text("copy source\n", encoding="utf-8")
    (parent / "status-source.txt").write_text("rename status source\n", encoding="utf-8")
    (parent / "hunks.txt").write_text(
        "".join(f"line {number}\n" for number in range(30)),
        encoding="utf-8",
    )
    _commit_all(parent, "tracked fixtures")
    completed = subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(child),
            "vendor/child",
        ],
        cwd=parent,
        check=False,
        capture_output=True,
        shell=False,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip(f"local submodules unavailable: {completed.stderr.strip()}")
    base_sha = _commit_all(parent, "add submodule")

    (parent / "alpha.txt").write_text("alpha changed\n", encoding="utf-8")
    (parent / "zeta.txt").write_text("zeta changed\n", encoding="utf-8")
    hunk_lines = (parent / "hunks.txt").read_text(encoding="utf-8").splitlines()
    hunk_lines[0] = "first hunk changed"
    hunk_lines[-1] = "last hunk changed"
    (parent / "hunks.txt").write_text("\n".join(hunk_lines) + "\n", encoding="utf-8")
    shutil.copyfile(parent / "copy-source.txt", parent / "copy-destination.txt")
    _git(parent, "mv", "status-source.txt", "status-destination.txt")
    _git(parent, "add", "copy-destination.txt", "hunks.txt")
    (parent / "vendor" / "child" / "base.txt").write_text(
        "dirty child worktree\n",
        encoding="utf-8",
    )

    order_file = parent / ".git-diff-order"
    order_file.write_text("zeta.txt\nalpha.txt\n", encoding="utf-8")
    baseline = capture_diff(
        parent,
        base_ref=base_sha,
        include_untracked=False,
        context_lines=0,
    )
    assert "Subproject commit" in baseline.patch
    assert "-dirty" in baseline.patch
    assert _by_path(baseline)["copy-destination.txt"].status == "A"

    overrides = {
        "core.abbrev": "4",
        "core.bigFileThreshold": "1",
        "diff.orderFile": str(order_file),
        "diff.noprefix": "true",
        "diff.mnemonicPrefix": "true",
        "diff.submodule": "log",
        "diff.algorithm": "histogram",
        "diff.indentHeuristic": "true",
        "diff.compactionHeuristic": "true",
        "diff.interHunkContext": "99",
        "diff.suppressBlankEmpty": "true",
        "diff.renames": "copies",
        "diff.renameLimit": "1",
        "diff.ignoreSubmodules": "all",
        "status.renames": "false",
        "status.renameLimit": "1",
        "submodule.vendor/child.ignore": "all",
    }
    for key, value in overrides.items():
        _git(parent, "config", key, value)

    configured = capture_diff(
        parent,
        base_ref=base_sha,
        include_untracked=False,
        context_lines=0,
    )

    assert configured.patch == baseline.patch
    assert configured.diff_sha256 == baseline.diff_sha256
    assert configured.changed_files == baseline.changed_files
    assert configured.working_tree_status == baseline.working_tree_status
    assert "diff --git a/" in configured.patch
    assert " b/" in configured.patch
    assert "Subproject commit" in configured.patch
    assert "-dirty" in configured.patch


@pytest.mark.parametrize("max_diff_chars", [0, -1, True, 1.5])
def test_max_diff_chars_must_be_a_positive_integer_before_git_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_diff_chars: object,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("Git must not run for invalid bounds")

    monkeypatch.setattr(diffing.subprocess, "run", explode)

    with pytest.raises(DiffCaptureError, match="max_diff_chars must be a positive integer"):
        capture_diff(tmp_path, base_ref="HEAD", max_diff_chars=max_diff_chars)  # type: ignore[arg-type]


@pytest.mark.parametrize("context_lines", [-1, 201, True, 1.5])
def test_context_lines_must_be_an_integer_from_zero_to_200_before_git_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    context_lines: object,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("Git must not run for invalid bounds")

    monkeypatch.setattr(diffing.subprocess, "run", explode)

    with pytest.raises(DiffCaptureError, match="context_lines must be an integer from 0 to 200"):
        capture_diff(tmp_path, base_ref="HEAD", context_lines=context_lines)  # type: ignore[arg-type]


def test_oversized_diff_reports_actual_limit_and_rough_tokens(tmp_path: Path) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "large.txt").write_text("x" * 200 + "\n", encoding="utf-8")

    with pytest.raises(
        DiffCaptureError,
        match=r"actual_chars=\d+; limit=40; rough_tokens=\d+",
    ):
        capture_diff(repo, base_ref=base_sha, max_diff_chars=40)


def test_all_git_calls_are_argument_arrays_without_shell_and_diffs_use_safe_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _init_repo(tmp_path)
    (repo / "base.txt").write_text("base\nchange\n", encoding="utf-8")
    original_run = subprocess.run
    calls: list[tuple[object, dict[str, object]]] = []

    def recording_run(args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, dict(kwargs)))
        return original_run(args, **kwargs)

    monkeypatch.setattr(diffing.subprocess, "run", recording_run)

    capture_diff(repo, base_ref=base_sha, context_lines=7)

    assert calls
    for args, kwargs in calls:
        assert isinstance(args, list)
        assert kwargs["shell"] is False
    diff_calls = [args for args, _ in calls if isinstance(args, list) and "diff" in args]
    assert diff_calls
    for args in diff_calls:
        assert "--find-renames" in args
        assert "--no-ext-diff" in args
        assert "--no-textconv" in args
        assert "--no-color" in args
        assert "--full-index" in args
        assert "--src-prefix=a/" in args
        assert "--dst-prefix=b/" in args
        assert "core.bigFileThreshold=512m" in args
        assert "diff.suppressBlankEmpty=false" in args
        assert "diff.compactionHeuristic=false" in args
        assert "--find-copies" not in args
    patch_calls = [
        args
        for args in diff_calls
        if not any(flag in args for flag in ("--name-status", "--raw", "--numstat"))
    ]
    assert patch_calls
    assert all("--unified=7" in args for args in patch_calls)
    assert all("--inter-hunk-context=0" in args for args in patch_calls)
    status_calls = [args for args in diff_calls if "--name-status" in args]
    assert status_calls
    assert all("-z" in args for args in status_calls)
    porcelain_calls = [
        args for args, _ in calls if isinstance(args, list) and "status" in args
    ]
    assert porcelain_calls
    assert all("status.renames=true" in args for args in porcelain_calls)
    assert all("status.renameLimit=1000" in args for args in porcelain_calls)


def test_git_errors_are_concise_and_do_not_echo_user_refs(tmp_path: Path) -> None:
    repo, _ = _init_repo(tmp_path)
    secret_ref = "refs/heads/token-super-secret-value"

    with pytest.raises(DiffCaptureError) as exc_info:
        capture_diff(repo, base_ref=secret_ref)

    message = str(exc_info.value)
    assert message == "Could not resolve the base ref to a commit"
    assert secret_ref not in message
