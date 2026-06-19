from pathlib import Path

from krystal_quorum.models import ClauseStatus, ReviewerOutput, Verdict
from krystal_quorum.persist import persist_run, plan_sha256
from krystal_quorum.reconcile import reconcile


def output() -> ReviewerOutput:
    return ReviewerOutput(
        reviewer="mock",
        round=1,
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
