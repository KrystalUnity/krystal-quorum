import json
from pathlib import Path

from krystal_quorum.models import ClauseStatus, ReviewerOutput, ReviewIssue, Verdict
from krystal_quorum.persist import persist_run, plan_sha256
from krystal_quorum.reconcile import reconcile


def output(reviewer: str = "mock", round_number: int = 1) -> ReviewerOutput:
    return ReviewerOutput(
        reviewer=reviewer,
        round=round_number,  # type: ignore[arg-type]
        verdict=Verdict.APPROVE,
        confidence=0.8,
        blocking_issues=[],
        suggestions=[],
        per_clause={"acceptance.1": ClauseStatus.SATISFIED},
        raw_response="{}",
        elapsed_seconds=0.1,
    )


def test_persist_run_writes_expected_files(tmp_path: Path):
    plan_text = "## Acceptance\n- Works"
    result = reconcile(
        plan_path="plan.md",
        plan_text=plan_text,
        reviewers_used=["mock"],
        round1_outputs=[output()],
        round2_outputs=[],
    )

    run_dir = persist_run(tmp_path, Path("plan.md"), plan_text, result)

    assert (run_dir / "plan_input.md").exists()
    assert (run_dir / "reconciled.json").exists()
    assert (run_dir / "summary.md").exists()
    assert (run_dir / "plan_input.sha256").read_text().strip() == plan_sha256(plan_text)


def test_persist_run_sanitizes_reviewer_filenames(tmp_path: Path):
    plan_text = "## Acceptance\n- Works"
    reviewer_id = "ollama:igorls/gemma-4-12B-it-heretic-GGUF:latest"
    result = reconcile(
        plan_path="plan.md",
        plan_text=plan_text,
        reviewers_used=[reviewer_id],
        round1_outputs=[output(reviewer_id)],
        round2_outputs=[output(reviewer_id, round_number=2)],
    )

    run_dir = persist_run(tmp_path, Path("plan.md"), plan_text, result)

    round1_files = list((run_dir / "round1").glob("*.json"))
    round2_files = list((run_dir / "round2").glob("*.json"))
    assert len(round1_files) == 1
    assert len(round2_files) == 1
    assert round1_files[0].name == round2_files[0].name
    assert "/" not in round1_files[0].name
    assert "\\" not in round1_files[0].name
    assert ":" not in round1_files[0].name
    assert json.loads(round1_files[0].read_text(encoding="utf-8"))["reviewer"] == reviewer_id


def test_persist_run_writes_issue_cluster_edges_to_json_and_summary(tmp_path: Path):
    plan_text = "## Rollback\n- Missing"
    issue_a = ReviewIssue(
        id="B1",
        section="Plan",
        claim="No rollback plan is described.",
        evidence="",
    )
    issue_b = ReviewIssue(
        id="B2",
        section="Plan",
        claim="Missing backout path if deployment fails.",
        evidence="",
    )
    result = reconcile(
        plan_path="plan.md",
        plan_text=plan_text,
        reviewers_used=["agy", "claude"],
        round1_outputs=[
            ReviewerOutput(
                reviewer="agy",
                round=1,
                verdict=Verdict.REVISE,
                confidence=0.8,
                blocking_issues=[issue_a],
                suggestions=[],
                per_clause={"rollback.plan": ClauseStatus.UNSATISFIED},
                raw_response="{}",
                elapsed_seconds=0.1,
            ),
            ReviewerOutput(
                reviewer="claude",
                round=1,
                verdict=Verdict.REVISE,
                confidence=0.8,
                blocking_issues=[issue_b],
                suggestions=[],
                per_clause={"rollback.plan": ClauseStatus.UNSATISFIED},
                raw_response="{}",
                elapsed_seconds=0.1,
            ),
        ],
        round2_outputs=[],
    )

    run_dir = persist_run(tmp_path, Path("plan.md"), plan_text, result)
    reconciled = json.loads((run_dir / "reconciled.json").read_text(encoding="utf-8"))
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")

    assert reconciled["schema_version"] == "1.2"
    assert reconciled["issue_clusters"][0]["edges"][0]["match_reason"] == (
        "shared topic rollback with absence intent; gap overlap: recovery"
    )
    assert "## Issue Clusters" in summary
    assert "gap overlap: recovery" in summary
