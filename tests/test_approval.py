import json
import os
import subprocess
from pathlib import Path
import string

import pytest
from pydantic import ValidationError

from krystal_quorum.approval import (
    ApprovalError,
    ApprovalReceipt,
    build_approval_receipt,
    canonical_json_bytes,
    canonical_json_sha256,
    load_and_validate_approval,
    prepare_bound_review,
    revalidate_bound_review,
)
from krystal_quorum.models import (
    ClauseStatus,
    DiversityReport,
    ReviewerFamily,
    ReviewerOutput,
    Verdict,
)
from krystal_quorum.persist import persist_run
from krystal_quorum.reconcile import reconcile


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Tests")
    plan = repo / "docs" / "plans" / "change.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "# Change\n\n## Acceptance Criteria\n\n- [AC-1] The command succeeds.\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "add plan")
    return repo, plan


def _result(plan: Path, verdict: Verdict = Verdict.APPROVE):
    output = ReviewerOutput(
        reviewer="mock",
        round=1,
        verdict=verdict,
        confidence=0.9,
        blocking_issues=[],
        suggestions=[],
        per_clause={"acceptance.1": ClauseStatus.SATISFIED},
        raw_response="{}",
        elapsed_seconds=0.1,
    )
    return reconcile(
        plan_path=str(plan),
        plan_text=plan.read_text(encoding="utf-8"),
        reviewers_used=["mock"],
        round1_outputs=[output],
        round2_outputs=[],
    )


def _approved_run(tmp_path: Path):
    repo, plan = _repo(tmp_path)
    out_dir = repo / ".krystal-quorum" / "reviews"
    state = prepare_bound_review(repo, plan, out_dir)
    result = _result(plan)
    receipt = build_approval_receipt(state, result)
    run_dir = persist_run(out_dir, plan, plan.read_text(encoding="utf-8"), result, receipt=receipt)
    return repo, plan, run_dir, receipt


def test_receipt_hash_uses_sorted_compact_utf8_json() -> None:
    payload = {"b": 2, "a": "caf\N{LATIN SMALL LETTER E WITH ACUTE}"}

    assert canonical_json_bytes(payload) == b'{"a":"caf\xc3\xa9","b":2}'
    assert canonical_json_sha256(payload) == (
        "6d25402cde044dae7bc06b10f117a4e1ad4b9068984aa262f46af63e330e7aa6"
    )


def test_prepare_bound_review_captures_repository_relative_baseline(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)

    state = prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")

    assert state.repo_root == repo.resolve()
    assert state.plan_path == "docs/plans/change.md"
    assert state.base_ref == "HEAD"
    assert state.base_sha == _git(repo, "rev-parse", "HEAD")
    assert [item.model_dump(mode="json") for item in state.commitments] == [
        {
            "id": "AC-1",
            "category": "acceptance",
            "text": "The command succeeds.",
            "source_line": 5,
        }
    ]


def test_prepare_bound_review_rejects_different_reviewer_input_snapshot(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)

    with pytest.raises(ApprovalError, match="changed before review"):
        prepare_bound_review(
            repo,
            plan,
            repo / "artifacts",
            plan_text="## Acceptance\n- Stale reviewer input\n",
        )


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_prepare_bound_review_compares_plan_bytes_to_head_when_status_is_hidden(
    tmp_path: Path, index_flag: str
) -> None:
    repo, plan = _repo(tmp_path)
    _git(repo, "update-index", index_flag, "docs/plans/change.md")
    plan.write_text(
        "# Change\n\n## Acceptance Criteria\n\n- [AC-1] Hidden local change.\n",
        encoding="utf-8",
    )
    assert _git(repo, "status", "--porcelain") == ""

    with pytest.raises(ApprovalError, match="HEAD plan bytes"):
        prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")


def test_prepare_bound_review_rejects_clean_filter_plan_byte_mismatch(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    _git(
        repo,
        "config",
        "filter.rewrite.clean",
        "python -c \"import sys; sys.stdout.write(sys.stdin.read().replace('WORKTREE', 'HEAD'))\"",
    )
    (repo / ".gitattributes").write_text(
        "docs/plans/change.md filter=rewrite\n",
        encoding="utf-8",
    )
    plan.write_text(
        "# Change\n\n## Acceptance Criteria\n\n- [AC-1] WORKTREE content.\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".gitattributes", "docs/plans/change.md")
    _git(repo, "commit", "-m", "add clean filter")
    assert _git(repo, "status", "--porcelain") == ""

    with pytest.raises(ApprovalError, match="HEAD plan bytes"):
        prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")


def test_prepare_bound_review_requires_plan_tracked_at_head(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    plan = repo / "untracked.md"
    plan.write_text("## Acceptance\n- Works\n", encoding="utf-8")

    with pytest.raises(ApprovalError, match="tracked at HEAD"):
        prepare_bound_review(repo, plan, repo / "artifacts")


@pytest.mark.parametrize("change", ["tracked", "untracked"])
def test_prepare_bound_review_requires_clean_repository(tmp_path: Path, change: str) -> None:
    repo, plan = _repo(tmp_path)
    if change == "tracked":
        (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
        _git(repo, "add", "tracked.txt")
        _git(repo, "commit", "-m", "add tracked")
        (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    else:
        (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    with pytest.raises(ApprovalError, match="clean"):
        prepare_bound_review(repo, plan, repo / "artifacts")


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_prepare_bound_review_rejects_hidden_sibling_tracked_change(
    tmp_path: Path, index_flag: str
) -> None:
    repo, plan = _repo(tmp_path)
    sibling = repo / "src" / "odd name.py"
    sibling.parent.mkdir()
    sibling.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "src/odd name.py")
    _git(repo, "commit", "-m", "add sibling source")
    _git(repo, "update-index", index_flag, "src/odd name.py")
    sibling.write_text("VALUE = 2\n", encoding="utf-8")
    assert _git(repo, "status", "--porcelain") == ""

    with pytest.raises(ApprovalError, match="assume-unchanged or skip-worktree"):
        prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")


def test_prepare_bound_review_accepts_unflagged_clean_sibling(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    sibling = repo / "src" / "module.py"
    sibling.parent.mkdir()
    sibling.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "src/module.py")
    _git(repo, "commit", "-m", "add clean sibling")

    state = prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")

    assert state.base_sha == _git(repo, "rev-parse", "HEAD")


def test_prepare_bound_review_excludes_only_configured_artifact_directory(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    out_dir = repo / "artifacts"
    out_dir.mkdir()
    (out_dir / "existing.json").write_text("{}", encoding="utf-8")

    state = prepare_bound_review(repo, plan, out_dir)

    assert state.artifact_dir == out_dir.resolve()
    (repo / "other.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ApprovalError, match="clean"):
        prepare_bound_review(repo, plan, out_dir)


def test_prepare_bound_review_treats_artifact_path_as_literal(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    out_dir = repo / "artifacts[1]"
    out_dir.mkdir()
    (out_dir / "existing.json").write_text("{}", encoding="utf-8")

    state = prepare_bound_review(repo, plan, out_dir)

    assert state.artifact_dir == out_dir.resolve()


def test_prepare_bound_review_rejects_repository_root_as_output(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)

    with pytest.raises(ApprovalError, match="repository root"):
        prepare_bound_review(repo, plan, repo)


def test_prepare_bound_review_rejects_output_inside_git_directory(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)

    with pytest.raises(ApprovalError, match="Git metadata"):
        prepare_bound_review(repo, plan, repo / ".git" / "quorum-reviews")


def test_prepare_bound_review_rejects_non_directory_existing_ancestor(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    tracked_file = repo / "tracked-file"
    tracked_file.write_text("not a directory\n", encoding="utf-8")
    _git(repo, "add", "tracked-file")
    _git(repo, "commit", "-m", "add blocking file")

    with pytest.raises(ApprovalError, match="existing ancestor must be a directory"):
        prepare_bound_review(repo, plan, tracked_file / "reviews")


def test_prepare_bound_review_rejects_linked_worktree_git_file_ancestor(
    tmp_path: Path,
) -> None:
    repo, _ = _repo(tmp_path)
    linked = tmp_path / "linked-worktree"
    try:
        _git(repo, "worktree", "add", "-b", "approval-linked-test", str(linked))
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"Git worktrees unavailable: {exc}")
    assert (linked / ".git").is_file()
    linked_plan = linked / "docs" / "plans" / "change.md"

    with pytest.raises(ApprovalError, match="existing ancestor must be a directory"):
        prepare_bound_review(linked, linked_plan, linked / ".git" / "reviews")


def test_prepare_bound_review_rejects_output_outside_repository(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)

    with pytest.raises(ApprovalError, match="inside the bound repository"):
        prepare_bound_review(repo, plan, tmp_path / "outside-reviews")


def test_prepare_bound_review_rejects_tracked_source_output_even_when_modified(
    tmp_path: Path,
) -> None:
    repo, plan = _repo(tmp_path)
    source = repo / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "src/module.py")
    _git(repo, "commit", "-m", "add source")
    source.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(ApprovalError, match="tracked path"):
        prepare_bound_review(repo, plan, repo / "src")


def test_prepare_bound_review_rejects_output_containing_tracked_gitkeep(
    tmp_path: Path,
) -> None:
    repo, plan = _repo(tmp_path)
    out_dir = repo / "artifacts"
    out_dir.mkdir()
    (out_dir / ".gitkeep").write_text("", encoding="utf-8")
    _git(repo, "add", "artifacts/.gitkeep")
    _git(repo, "commit", "-m", "track artifact placeholder")

    with pytest.raises(ApprovalError, match="tracked path"):
        prepare_bound_review(repo, plan, out_dir)


def test_prepare_bound_review_does_not_exclude_prefix_sibling(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    out_dir = repo / "art"
    sibling = repo / "artifacts"
    sibling.mkdir()
    (sibling / "unexpected.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ApprovalError, match="clean"):
        prepare_bound_review(repo, plan, out_dir)


def test_prepare_bound_review_rejects_existing_symlink_escape(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = repo / "linked-reviews"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(ApprovalError, match="inside the bound repository"):
        prepare_bound_review(repo, plan, link)


@pytest.mark.skipif(os.name != "nt", reason="Windows path case semantics")
def test_prepare_bound_review_accepts_windows_case_variant_inside_repo(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    case_repo = Path(str(repo).swapcase())
    case_plan = case_repo / plan.relative_to(repo)
    out_dir = case_repo / ".krystal-quorum" / "reviews"

    state = prepare_bound_review(case_repo, case_plan, out_dir)

    assert state.repo_root == repo.resolve()


@pytest.mark.skipif(os.name != "nt", reason="Windows path case semantics")
def test_prepare_bound_review_rejects_tracked_output_with_windows_case_variant(
    tmp_path: Path,
) -> None:
    repo, plan = _repo(tmp_path)
    source = repo / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "src/module.py")
    _git(repo, "commit", "-m", "add source")

    with pytest.raises(ApprovalError, match="tracked path"):
        prepare_bound_review(repo, plan, repo / "SRC")


@pytest.mark.skipif(os.name != "nt", reason="Windows drive semantics")
def test_prepare_bound_review_rejects_output_on_different_windows_drive(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    different_roots = [
        Path(f"{letter}:\\")
        for letter in string.ascii_uppercase
        if f"{letter}:".casefold() != repo.drive.casefold() and Path(f"{letter}:\\").exists()
    ]
    if not different_roots:
        pytest.skip("no second Windows drive is mounted")

    with pytest.raises(ApprovalError, match="inside the bound repository"):
        prepare_bound_review(repo, plan, different_roots[0] / "krystal-quorum-reviews")


def test_prepare_bound_review_rejects_plan_without_commitments(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    plan.write_text("# Change\n\nNo recognized commitments.\n", encoding="utf-8")
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "remove commitments")

    with pytest.raises(ApprovalError, match="no required commitments"):
        prepare_bound_review(repo, plan, repo / "artifacts")


def test_prepare_bound_review_rejects_plan_outside_repository(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    plan = tmp_path / "outside.md"
    plan.write_text("## Acceptance\n- Works\n", encoding="utf-8")

    with pytest.raises(ApprovalError, match="inside"):
        prepare_bound_review(repo, plan, repo / "artifacts")


@pytest.mark.parametrize("mutation", ["head", "plan", "worktree"])
def test_revalidate_bound_review_rejects_concurrent_changes(
    tmp_path: Path, mutation: str
) -> None:
    repo, plan = _repo(tmp_path)
    out_dir = repo / "artifacts"
    state = prepare_bound_review(repo, plan, out_dir)

    if mutation == "head":
        (repo / "new.txt").write_text("new\n", encoding="utf-8")
        _git(repo, "add", "new.txt")
        _git(repo, "commit", "-m", "move head")
    elif mutation == "plan":
        plan.write_text("## Acceptance\n- Changed\n", encoding="utf-8")
    else:
        (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ApprovalError, match="changed during review"):
        revalidate_bound_review(state)


def test_revalidate_bound_review_compares_hidden_plan_change_to_head(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    state = prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")
    _git(repo, "update-index", "--assume-unchanged", "docs/plans/change.md")
    plan.write_text(
        "# Change\n\n## Acceptance Criteria\n\n- [AC-1] Hidden after review.\n",
        encoding="utf-8",
    )
    assert _git(repo, "status", "--porcelain") == ""

    with pytest.raises(ApprovalError, match="HEAD plan bytes"):
        revalidate_bound_review(state)


def test_build_approval_receipt_requires_approve(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    state = prepare_bound_review(repo, plan, repo / "artifacts")

    with pytest.raises(ApprovalError, match="APPROVE"):
        build_approval_receipt(state, _result(plan, Verdict.REVISE))

    payload = build_approval_receipt(state, _result(plan)).model_dump(mode="json")
    payload["verdict"] = "REVISE"
    with pytest.raises(ValidationError):
        ApprovalReceipt.model_validate(payload)


@pytest.mark.parametrize(
    "forbidden_text",
    [
        "Use sk-proj-abcdefghijklmnopqrstuvwxyz123456.",
        "Read configuration from /home/operator/private.json.",
        r"Read configuration from C:\Users\operator\private.json.",
        "Fetch the contract from https://example.test/private-plan.",
    ],
)
def test_prepare_bound_review_rejects_forbidden_commitment_content(
    tmp_path: Path, forbidden_text: str
) -> None:
    repo, plan = _repo(tmp_path)
    plan.write_text(
        f"# Change\n\n## Acceptance Criteria\n\n- [AC-1] {forbidden_text}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "add forbidden receipt content")

    with pytest.raises(ApprovalError, match="forbidden receipt content"):
        prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")


@pytest.mark.parametrize(
    "forbidden_text",
    [
        "Upload evidence to s3://private-bucket/change.json.",
        "Connect to wss://reviewer.example.test/socket.",
        "Read file:///home/operator/private.json.",
        "Clone ssh://git@example.test/private/repo.git.",
        "Clone git@example.test:private/repo.git.",
        "Read,/etc/private.conf before review.",
        r"Read;C:\Users\operator\private.json before review.",
        r"Read,(\\server\share\private.json) before review.",
        "Read,(~/private/config) before review.",
    ],
)
def test_prepare_bound_review_rejects_uri_and_path_boundary_bypasses(
    tmp_path: Path, forbidden_text: str
) -> None:
    repo, plan = _repo(tmp_path)
    plan.write_text(
        f"# Change\n\n## Acceptance Criteria\n\n- [AC-1] {forbidden_text}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "add receipt bypass")

    with pytest.raises(ApprovalError, match="forbidden receipt content"):
        prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")


@pytest.mark.parametrize(
    "forbidden_text",
    [
        "config=/etc/private",
        r"output=C:\private",
        "home=~/private",
        "read>/etc/private",
    ],
)
def test_prepare_bound_review_rejects_symbol_delimited_absolute_paths(
    tmp_path: Path, forbidden_text: str
) -> None:
    repo, plan = _repo(tmp_path)
    plan.write_text(
        f"# Change\n\n## Acceptance Criteria\n\n- [AC-1] {forbidden_text}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "add symbol-delimited absolute path")

    with pytest.raises(ApprovalError, match="forbidden receipt content"):
        prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")


@pytest.mark.parametrize(
    "forbidden_text",
    [
        "//example.test/private must not be persisted.",
        "Fetch,(//example.test/private) before review.",
    ],
)
def test_prepare_bound_review_rejects_protocol_relative_remote_urls(
    tmp_path: Path, forbidden_text: str
) -> None:
    repo, plan = _repo(tmp_path)
    plan.write_text(
        f"# Change\n\n## Acceptance Criteria\n\n- [AC-1] {forbidden_text}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "add protocol-relative remote")

    with pytest.raises(ApprovalError, match="forbidden receipt content"):
        prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")


@pytest.mark.parametrize(
    ("reviewer", "family"),
    [
        ("sk-proj-abcdefghijklmnopqrstuvwxyz123456", "codex"),
        ("/home/operator/reviewer", "codex"),
        ("command:local", r"C:\Users\operator\model"),
        ("https://reviewer.example.test/model", "codex"),
    ],
)
def test_build_approval_receipt_rejects_forbidden_reviewer_metadata(
    tmp_path: Path, reviewer: str, family: str
) -> None:
    repo, plan = _repo(tmp_path)
    state = prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")
    result = _result(plan).model_copy(
        update={
            "reviewers_used": [reviewer],
            "diversity": DiversityReport(
                status="ok",
                reviewers=[
                    ReviewerFamily(reviewer=reviewer, backend="test", family=family)
                ],
            ),
        }
    )

    with pytest.raises(ApprovalError, match="forbidden receipt content"):
        build_approval_receipt(state, result)


def test_receipt_content_allows_repository_relative_paths_and_model_ids(
    tmp_path: Path,
) -> None:
    repo, plan = _repo(tmp_path)
    plan.write_text(
        "# Change\n\n## Acceptance Criteria\n\n"
        "- [AC-1] Update src/krystal_quorum/cli.py for the selected model; "
        "keep ../relative, and/or prose, ratio 3/4, and version 1.2.3 ordinary.\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "add relative commitment")
    state = prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")
    reviewer = "ollama:meta/llama-3.1:8b"
    family = "meta/llama-3.1"
    result = _result(plan).model_copy(
        update={
            "reviewers_used": [reviewer],
            "diversity": DiversityReport(
                status="ok",
                reviewers=[
                    ReviewerFamily(reviewer=reviewer, backend="ollama", family=family)
                ],
            ),
        }
    )

    receipt = build_approval_receipt(state, result)

    assert receipt.reviewers_used == [reviewer]
    assert receipt.reviewer_families == [family]


def test_receipt_content_allows_unicode_repository_relative_path(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    plan.write_text(
        "# Change\n\n## Acceptance Criteria\n\n"
        "- [AC-1] Update docs/caf\N{LATIN SMALL LETTER E WITH ACUTE}/menu.md.\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "add unicode relative path")

    state = prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")

    assert state.commitments[0].text == "Update docs/caf\N{LATIN SMALL LETTER E WITH ACUTE}/menu.md."


def test_receipt_content_allows_unicode_model_id(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    state = prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")
    reviewer = "ollama:\N{CJK UNIFIED IDEOGRAPH-6A21}\N{CJK UNIFIED IDEOGRAPH-578B}/\N{CJK UNIFIED IDEOGRAPH-4E03}"
    family = "\N{CJK UNIFIED IDEOGRAPH-6A21}\N{CJK UNIFIED IDEOGRAPH-578B}/\N{CJK UNIFIED IDEOGRAPH-4E03}"
    result = _result(plan).model_copy(
        update={
            "reviewers_used": [reviewer],
            "diversity": DiversityReport(
                status="ok",
                reviewers=[
                    ReviewerFamily(reviewer=reviewer, backend="ollama", family=family)
                ],
            ),
        }
    )

    receipt = build_approval_receipt(state, result)

    assert receipt.reviewers_used == [reviewer]
    assert receipt.reviewer_families == [family]


def test_receipt_content_allows_nfd_repository_relative_path(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    relative_path = "docs/cafe\u0301/menu.md"
    plan.write_text(
        "# Change\n\n## Acceptance Criteria\n\n"
        f"- [AC-1] Update {relative_path}.\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "add nfd relative path")

    state = prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")

    assert state.commitments[0].text == f"Update {relative_path}."


def test_receipt_content_allows_symbol_model_id(tmp_path: Path) -> None:
    repo, plan = _repo(tmp_path)
    state = prepare_bound_review(repo, plan, repo / ".krystal-quorum" / "reviews")
    reviewer = "ollama:\N{ARTIST PALETTE}/model"
    family = "\N{ARTIST PALETTE}/model"
    result = _result(plan).model_copy(
        update={
            "reviewers_used": [reviewer],
            "diversity": DiversityReport(
                status="ok",
                reviewers=[
                    ReviewerFamily(reviewer=reviewer, backend="ollama", family=family)
                ],
            ),
        }
    )

    receipt = build_approval_receipt(state, result)

    assert receipt.reviewers_used == [reviewer]
    assert receipt.reviewer_families == [family]


def test_receipt_reconciled_hash_matches_exact_sibling_payload(tmp_path: Path) -> None:
    repo, plan, run_dir, receipt = _approved_run(tmp_path)
    reconciled = json.loads((run_dir / "reconciled.json").read_text(encoding="utf-8"))

    assert receipt.reconciled_sha256 == canonical_json_sha256(reconciled)
    assert load_and_validate_approval(run_dir / "approval.json", plan, repo) == receipt


def test_loader_rejects_missing_or_mismatched_sibling_reconciled(tmp_path: Path) -> None:
    repo, plan, run_dir, _ = _approved_run(tmp_path)
    reconciled_path = run_dir / "reconciled.json"
    reconciled_path.unlink()
    with pytest.raises(ApprovalError, match="sibling reconciled.json"):
        load_and_validate_approval(run_dir / "approval.json", plan, repo)

    reconciled_path.write_text('{"merged_verdict":"APPROVE"}', encoding="utf-8")
    with pytest.raises(ApprovalError, match="reconciled hash"):
        load_and_validate_approval(run_dir / "approval.json", plan, repo)


def test_loader_rejects_altered_plan_and_commitments(tmp_path: Path) -> None:
    repo, plan, run_dir, _ = _approved_run(tmp_path)
    approval_path = run_dir / "approval.json"

    plan.write_text("## Acceptance Criteria\n- [AC-1] Altered.\n", encoding="utf-8")
    with pytest.raises(ApprovalError, match="plan hash"):
        load_and_validate_approval(approval_path, plan, repo)

    _git(repo, "restore", "docs/plans/change.md")
    receipt_payload = json.loads(approval_path.read_text(encoding="utf-8"))
    receipt_payload["commitments"][0]["text"] = "Altered."
    approval_path.write_text(json.dumps(receipt_payload), encoding="utf-8")
    with pytest.raises(ApprovalError, match="commitments"):
        load_and_validate_approval(approval_path, plan, repo)


def test_loader_rejects_valid_resolvable_baseline_with_different_plan_blob(
    tmp_path: Path,
) -> None:
    repo, plan = _repo(tmp_path)
    different_plan_sha = _git(repo, "rev-parse", "HEAD")
    plan.write_text(
        "# Change\n\n## Acceptance Criteria\n\n- [AC-1] Current approved plan.\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plans/change.md")
    _git(repo, "commit", "-m", "update approved plan")
    out_dir = repo / ".krystal-quorum" / "reviews"
    state = prepare_bound_review(repo, plan, out_dir)
    result = _result(plan)
    receipt = build_approval_receipt(state, result)
    run_dir = persist_run(
        out_dir,
        plan,
        plan.read_text(encoding="utf-8"),
        result,
        receipt=receipt,
    )
    approval_path = run_dir / "approval.json"
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    payload["base_sha"] = different_plan_sha
    approval_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ApprovalError, match="baseline plan"):
        load_and_validate_approval(approval_path, plan, repo)


def test_loader_rejects_valid_non_ancestor_implementation_head(tmp_path: Path) -> None:
    repo, plan, run_dir, _ = _approved_run(tmp_path)
    tree_sha = _git(repo, "rev-parse", "HEAD^{tree}")
    non_ancestor_sha = _git(repo, "commit-tree", tree_sha, "-m", "divergent root")

    with pytest.raises(ApprovalError, match="not an ancestor"):
        load_and_validate_approval(
            run_dir / "approval.json",
            plan,
            repo,
            head_sha=non_ancestor_sha,
        )


def test_loader_rejects_altered_receipt_and_non_approve_reconciliation(tmp_path: Path) -> None:
    repo, plan, run_dir, _ = _approved_run(tmp_path)
    approval_path = run_dir / "approval.json"
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    approval_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ApprovalError, match="Invalid approval receipt"):
        load_and_validate_approval(approval_path, plan, repo)

    payload.pop("unexpected")
    reconciled_path = run_dir / "reconciled.json"
    reconciled = json.loads(reconciled_path.read_text(encoding="utf-8"))
    reconciled["merged_verdict"] = "REVISE"
    reconciled_path.write_text(json.dumps(reconciled), encoding="utf-8")
    payload["reconciled_sha256"] = canonical_json_sha256(reconciled)
    approval_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ApprovalError, match="APPROVE"):
        load_and_validate_approval(approval_path, plan, repo)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_version", "9.9.9"),
        ("created_at", "2020-01-01T00:00:00+00:00"),
        ("reviewers_used", ["altered"]),
        ("reviewer_families", ["altered"]),
        ("diversity", "low"),
    ],
)
def test_loader_rejects_receipt_metadata_altered_from_reconciliation(
    tmp_path: Path, field: str, value: object
) -> None:
    repo, plan, run_dir, _ = _approved_run(tmp_path)
    approval_path = run_dir / "approval.json"
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    payload[field] = value
    approval_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ApprovalError, match="receipt|reconciliation"):
        load_and_validate_approval(approval_path, plan, repo)
