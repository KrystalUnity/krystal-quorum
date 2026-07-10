from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest
from typer.testing import CliRunner

import krystal_quorum.diff_service as diff_service_module
from krystal_quorum.cli import app


PLAN_TEXT = """# Greeting implementation

## Scope
- [SCOPE-1] Update `src/feature.py` so `greet()` returns the ready state.

## Acceptance Criteria
- [AC-1] `greet()` returns `\"ready\"` after implementation.

## Tests
- [TEST-1] The verified diff records deterministic evidence for the implementation.
"""
REVIEWERS = ["command:alpha", "command:beta"]
REVIEWER_FAMILIES = ["golden-alpha", "golden-beta"]
PLAN_CLAUSES = {
    "acceptance.criteria",
    "rollback.plan",
    "tests.verification",
    "safety.assumptions",
    "security.risk",
    "dependencies.scope",
    "observability.plan",
}
DIFF_CLAUSES = {
    "scope.alignment",
    "tests.coverage",
    "security.alignment",
    "dependencies.alignment",
    "rollback.implemented",
    "observability.implemented",
}
EXPECTED_COMMITMENTS = [
    {
        "id": "SCOPE-1",
        "category": "scope",
        "text": "Update `src/feature.py` so `greet()` returns the ready state.",
        "source_line": 4,
    },
    {
        "id": "AC-1",
        "category": "acceptance",
        "text": "`greet()` returns `\"ready\"` after implementation.",
        "source_line": 7,
    },
    {
        "id": "TEST-1",
        "category": "tests",
        "text": "The verified diff records deterministic evidence for the implementation.",
        "source_line": 10,
    },
]


@dataclass(frozen=True)
class GoldenRun:
    repo: Path
    plan: Path
    out_dir: Path
    reviewer_config: Path
    review_output: dict[str, object]
    approval_path: Path
    plan_run_dir: Path
    baseline_sha: str
    implementation_sha: str
    expected_patch: str


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_committed_patch(repo: Path, baseline_sha: str, implementation_sha: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "-c",
            "core.bigFileThreshold=512m",
            "-c",
            "diff.suppressBlankEmpty=false",
            "-c",
            "diff.compactionHeuristic=false",
            "diff",
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
            "--unified=20",
            "--inter-hunk-context=0",
            baseline_sha,
            implementation_sha,
            "--",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    patch = completed.stdout.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return f"### krystal-quorum diff: committed\n{patch}\n"


def _write_expectations(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_command_reviewer(path: Path) -> None:
    path.write_text(
        dedent(
            '''\
            import json
            import sys

            PLAN_CLAUSES = (
                "acceptance.criteria",
                "rollback.plan",
                "tests.verification",
                "safety.assumptions",
                "security.risk",
                "dependencies.scope",
                "observability.plan",
            )
            DIFF_CLAUSES = (
                "scope.alignment",
                "tests.coverage",
                "security.alignment",
                "dependencies.alignment",
                "rollback.implemented",
                "observability.implemented",
            )

            def failure_payload(claim, *, diff_review):
                if diff_review:
                    return {
                        "verdict": "ABSTAIN",
                        "confidence": 0.0,
                        "commitment_coverage": [],
                        "scope_findings": [],
                        "blocking_issues": [
                            {
                                "id": "GOLDEN-INPUT",
                                "section": "runtime",
                                "claim": claim,
                                "evidence": "deterministic golden input validation failed",
                            }
                        ],
                        "suggestions": [],
                        "per_clause": {key: "UNCLEAR" for key in DIFF_CLAUSES},
                    }
                return {
                    "verdict": "REVISE",
                    "confidence": 1.0,
                    "blocking_issues": [
                        {
                            "id": "GOLDEN-PLAN",
                            "section": "runtime",
                            "claim": claim,
                            "evidence": "deterministic golden plan validation failed",
                        }
                    ],
                    "suggestions": [],
                    "per_clause": {key: "UNCLEAR" for key in PLAN_CLAUSES},
                }

            def parse_container(prompt, start, end, label):
                if start not in prompt or end not in prompt:
                    raise ValueError(f"missing {label} container")
                raw = prompt.split(start, 1)[1].split(end, 1)[0]
                container = json.loads(raw)
                if not isinstance(container, dict):
                    raise ValueError(f"{label} container must be an object")
                return container

            def exact_diff_input(prompt, expectations):
                commitments_container = parse_container(
                    prompt,
                    "UNTRUSTED COMMITMENTS (JSON):\\n",
                    "\\nEND UNTRUSTED COMMITMENTS",
                    "commitments",
                )
                review_input_container = parse_container(
                    prompt,
                    "UNTRUSTED REVIEW INPUT (JSON):\\n",
                    "\\nEND UNTRUSTED REVIEW INPUT",
                    "review input",
                )
                if set(commitments_container) != {"commitments"}:
                    raise ValueError("commitments container has unexpected keys")
                if set(review_input_container) != {"review_input"}:
                    raise ValueError("review input container has unexpected keys")

                commitments = commitments_container["commitments"]
                delivered_text = review_input_container["review_input"]
                if not isinstance(delivered_text, str):
                    raise ValueError("delivered review input must be a JSON string")
                delivered = json.loads(delivered_text)
                expected = expectations.get("review_input")
                if not isinstance(delivered, dict) or not isinstance(expected, dict):
                    raise ValueError("delivered and expected review inputs must be objects")

                checks = (
                    ("review kind", delivered.get("review_kind"), expected.get("review_kind")),
                    ("plan and approval binding", delivered.get("plan"), expected.get("plan")),
                    ("commitments", delivered.get("commitments"), expected.get("commitments")),
                    ("Git base/head binding", delivered.get("git"), expected.get("git")),
                    (
                        "authoritative changed file",
                        delivered.get("changed_files"),
                        expected.get("changed_files"),
                    ),
                    ("patch", delivered.get("patch"), expected.get("patch")),
                )
                for label, actual, wanted in checks:
                    if actual != wanted:
                        raise ValueError(f"{label} does not match exact expectation")
                if commitments != expected["commitments"]:
                    raise ValueError("prompt commitments do not match review input commitments")
                if delivered != expected:
                    raise ValueError("review input has unexpected or missing fields")
                return commitments

            def exact_plan_text(prompt, expected):
                start = "PLAN:\\n---\\n"
                if start not in prompt:
                    raise ValueError("missing plan envelope")
                tail = prompt.rsplit(start, 1)[1]
                round_suffix = "\\n---\\n\\n" if "performing Round 2 cross-audit" in prompt else "\\n---\\n"
                if tail != f"{expected}{round_suffix}":
                    raise ValueError("delivered plan differs from exact PLAN_TEXT")

            prompt = sys.stdin.read()
            diff_review = "UNTRUSTED COMMITMENTS (JSON):\\n" in prompt
            try:
                with open(sys.argv[1], encoding="utf-8") as handle:
                    expectations = json.load(handle)
                if diff_review:
                    commitments = exact_diff_input(prompt, expectations)
                else:
                    exact_plan_text(prompt, expectations["plan_text"])
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
                prefix = "golden review input mismatch" if diff_review else "golden plan text mismatch"
                payload = failure_payload(f"{prefix}: {exc}", diff_review=diff_review)
            else:
                if diff_review:
                    payload = {
                        "verdict": "APPROVE",
                        "confidence": 0.93,
                        "commitment_coverage": [
                            {
                                "commitment_id": item["id"],
                                "status": "IMPLEMENTED",
                                "claim": f"{item['id']} is implemented by the greeting change.",
                                "evidence": "src/feature.py:1",
                                "path": "src/feature.py",
                                "line_start": 1,
                            }
                            for item in commitments
                        ],
                        "scope_findings": [],
                        "blocking_issues": [],
                        "suggestions": [],
                        "per_clause": {
                            "scope.alignment": "SATISFIED",
                            "tests.coverage": "SATISFIED",
                            "security.alignment": "N/A",
                            "dependencies.alignment": "N/A",
                            "rollback.implemented": "N/A",
                            "observability.implemented": "N/A",
                        },
                    }
                else:
                    payload = {
                        "verdict": "APPROVE",
                        "confidence": 0.93,
                        "blocking_issues": [],
                        "suggestions": [],
                        "per_clause": {
                            "acceptance.criteria": "SATISFIED",
                            "rollback.plan": "N/A",
                            "tests.verification": "SATISFIED",
                            "safety.assumptions": "N/A",
                            "security.risk": "N/A",
                            "dependencies.scope": "N/A",
                            "observability.plan": "N/A",
                        },
                    }

            print("<json>")
            print(json.dumps(payload, sort_keys=True))
            print("</json>")
            '''
        ),
        encoding="utf-8",
    )


def _write_reviewer_config(
    path: Path,
    reviewer_script: Path,
    expectations_path: Path,
) -> None:
    command = json.dumps([sys.executable, str(reviewer_script), str(expectations_path)])
    path.write_text(
        dedent(
            f'''\
            [reviewers.alpha]
            type = "command"
            command = {command}
            family = "golden-alpha"
            data_boundary = "local"

            [reviewers.beta]
            type = "command"
            command = {command}
            family = "golden-beta"
            data_boundary = "local"
            '''
        ),
        encoding="utf-8",
    )


def _assert_reviewer_artifacts(
    run_dir: Path,
    *,
    clauses: set[str],
    diff_review: bool,
) -> None:
    required_keys = {
        "reviewer",
        "round",
        "verdict",
        "confidence",
        "blocking_issues",
        "suggestions",
        "per_clause",
        "raw_response",
        "elapsed_seconds",
        "retries",
    }
    if diff_review:
        required_keys.update({"commitment_coverage", "scope_findings"})

    for round_number in (1, 2):
        files = sorted((run_dir / f"round{round_number}").glob("*.json"))
        assert len(files) == 2
        outputs = [_load_json(path) for path in files]
        assert all(isinstance(output, dict) for output in outputs)
        assert {output["reviewer"] for output in outputs} == set(REVIEWERS)
        for output in outputs:
            assert set(output) == required_keys
            assert output["round"] == round_number
            assert output["verdict"] == "APPROVE"
            assert output["confidence"] == 0.93
            assert output["blocking_issues"] == []
            assert output["suggestions"] == []
            assert set(output["per_clause"]) == clauses
            assert output["retries"] == 0
            response_lines = output["raw_response"].splitlines()
            assert response_lines[0] == "<json>"
            assert response_lines[-1] == "</json>"
            if diff_review:
                assert output["scope_findings"] == []
                assert output["commitment_coverage"] == [
                    {
                        "commitment_id": item["id"],
                        "status": "IMPLEMENTED",
                        "claim": f"{item['id']} is implemented by the greeting change.",
                        "evidence": "src/feature.py:1",
                        "path": "src/feature.py",
                        "line_start": 1,
                    }
                    for item in EXPECTED_COMMITMENTS
                ]


def _prepare_approved_implementation(tmp_path: Path) -> GoldenRun:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Golden Test")
    _git(repo, "config", "core.autocrlf", "false")

    plan = repo / "docs" / "plan.md"
    feature = repo / "src" / "feature.py"
    plan.parent.mkdir()
    feature.parent.mkdir()
    plan.write_text(PLAN_TEXT, encoding="utf-8")
    feature.write_text('def greet() -> str:\n    return "pending"\n', encoding="utf-8")
    (repo / ".gitignore").write_text(".krystal-quorum/\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline with approved plan")
    baseline_sha = _git(repo, "rev-parse", "HEAD")

    reviewer_script = tmp_path / "golden_reviewer.py"
    reviewer_config = tmp_path / "krystal-quorum.toml"
    expectations_path = tmp_path / "golden_expectations.json"
    _write_expectations(expectations_path, {"plan_text": PLAN_TEXT})
    _write_command_reviewer(reviewer_script)
    _write_reviewer_config(reviewer_config, reviewer_script, expectations_path)
    out_dir = repo / ".krystal-quorum" / "reviews"
    runner = CliRunner()

    review_result = runner.invoke(
        app,
        [
            "review",
            str(plan),
            "--bind-repo",
            str(repo),
            "--reviewers",
            ",".join(REVIEWERS),
            "--config",
            str(reviewer_config),
            "--out-dir",
            str(out_dir),
            "--round2",
            "--require-diversity",
            "--format",
            "json",
        ],
    )

    assert review_result.exit_code == 0, review_result.output
    review_output = json.loads(review_result.stdout)
    approval_path = Path(review_output["approval_path"])
    plan_run_dir = Path(review_output["output_dir"])

    feature.write_text('def greet() -> str:\n    return "ready"\n', encoding="utf-8")
    _git(repo, "add", "src/feature.py")
    _git(repo, "commit", "-m", "implement approved greeting")
    implementation_sha = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "status", "--porcelain") == ""
    expected_patch = _expected_committed_patch(repo, baseline_sha, implementation_sha)
    approval = _load_json(approval_path)
    assert isinstance(approval, dict)
    plan_sha256 = hashlib.sha256(PLAN_TEXT.encode("utf-8")).hexdigest()
    _write_expectations(
        expectations_path,
        {
            "plan_text": PLAN_TEXT,
            "review_input": {
                "review_kind": "diff",
                "plan": {
                    "path": "docs/plan.md",
                    "sha256": plan_sha256,
                    "approval_sha256": _canonical_sha256(approval),
                    "provenance": "verified_receipt",
                    "text": PLAN_TEXT,
                },
                "commitments": [{**item, "group": None} for item in EXPECTED_COMMITMENTS],
                "git": {
                    "base_ref": baseline_sha,
                    "base_sha": baseline_sha,
                    "head_ref": implementation_sha,
                    "head_sha": implementation_sha,
                    "merge_base_sha": None,
                    "comparison": "committed",
                    "include_untracked": True,
                    "working_tree_status": [],
                },
                "changed_files": [
                    {
                        "status": "M",
                        "path": "src/feature.py",
                        "old_path": None,
                        "kind": "text",
                        "source": "committed",
                    }
                ],
                "patch": expected_patch,
            },
        },
    )

    return GoldenRun(
        repo=repo,
        plan=plan,
        out_dir=out_dir,
        reviewer_config=reviewer_config,
        review_output=review_output,
        approval_path=approval_path,
        plan_run_dir=plan_run_dir,
        baseline_sha=baseline_sha,
        implementation_sha=implementation_sha,
        expected_patch=expected_patch,
    )


def _invoke_diff(golden: GoldenRun):
    return CliRunner().invoke(
        app,
        [
            "diff",
            "--plan",
            str(golden.plan),
            "--approval",
            str(golden.approval_path),
            "--head",
            golden.implementation_sha,
            "--repo",
            str(golden.repo),
            "--reviewers",
            ",".join(REVIEWERS),
            "--config",
            str(golden.reviewer_config),
            "--out-dir",
            str(golden.out_dir),
            "--round2",
            "--require-diversity",
            "--format",
            "json",
        ],
    )


def test_golden_plan_reviewer_rejects_plan_text_other_than_exact_fixture(
    tmp_path: Path,
) -> None:
    reviewer_script = tmp_path / "golden_reviewer.py"
    expectations_path = tmp_path / "golden_expectations.json"
    _write_command_reviewer(reviewer_script)
    _write_expectations(expectations_path, {"plan_text": PLAN_TEXT})

    completed = subprocess.run(
        [sys.executable, str(reviewer_script), str(expectations_path)],
        input="PLAN:\n---\n# Different plan\n---\n",
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout.split("<json>", 1)[1].split("</json>", 1)[0])

    assert payload["verdict"] == "REVISE"
    assert "golden plan text mismatch" in payload["blocking_issues"][0]["claim"]


@pytest.mark.parametrize("corruption", ["empty", "missing_patch"])
def test_golden_reviewers_reject_corrupted_delivered_review_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    golden = _prepare_approved_implementation(tmp_path)
    real_build_review_input = diff_service_module._build_review_input

    def corrupt_review_input(*args, **kwargs) -> str:
        review_input = real_build_review_input(*args, **kwargs)
        if corruption == "empty":
            return "{}"
        payload = json.loads(review_input)
        del payload["patch"]
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    monkeypatch.setattr(diff_service_module, "_build_review_input", corrupt_review_input)

    result = _invoke_diff(golden)

    assert result.exit_code == 3, result.output
    output = json.loads(result.stdout)
    assert output["verdict"] == "ABSTAIN"
    run_dir = Path(output["output_dir"])
    for round_number in (1, 2):
        reviewer_outputs = [
            _load_json(path) for path in sorted((run_dir / f"round{round_number}").glob("*.json"))
        ]
        assert len(reviewer_outputs) == 2
        assert all(item["verdict"] == "ABSTAIN" for item in reviewer_outputs)
        assert all(
            "golden review input mismatch" in item["blocking_issues"][0]["claim"]
            for item in reviewer_outputs
        )


def test_bound_plan_to_verified_diff_persists_complete_auditable_evidence(
    tmp_path: Path,
) -> None:
    golden = _prepare_approved_implementation(tmp_path)
    out_dir = golden.out_dir
    review_output = golden.review_output
    approval_path = golden.approval_path
    plan_run_dir = golden.plan_run_dir
    baseline_sha = golden.baseline_sha
    implementation_sha = golden.implementation_sha

    assert review_output == {
        "schema_version": "1.2",
        "verdict": "APPROVE",
        "confidence": 0.93,
        "reviewers_used": REVIEWERS,
        "diversity": "ok",
        "diversity_reason": None,
        "diversity_reviewers": [
            {"reviewer": REVIEWERS[0], "backend": "command", "family": REVIEWER_FAMILIES[0]},
            {"reviewer": REVIEWERS[1], "backend": "command", "family": REVIEWER_FAMILIES[1]},
        ],
        "abstained_reviewers": [],
        "unresolved_for_human": [],
        "output_dir": review_output["output_dir"],
        "round2_delta": 0,
        "round2_comparisons": [
            {
                "reviewer": reviewer,
                "round1": "APPROVE",
                "round2": "APPROVE",
                "comparable": True,
                "changed": False,
            }
            for reviewer in REVIEWERS
        ],
        "approval_path": review_output["approval_path"],
    }
    assert approval_path == plan_run_dir / "approval.json"
    assert plan_run_dir.parent == out_dir
    assert plan_run_dir.is_dir()

    plan_sha256 = hashlib.sha256(PLAN_TEXT.encode("utf-8")).hexdigest()
    approval = _load_json(approval_path)
    plan_reconciled = _load_json(plan_run_dir / "reconciled.json")
    assert isinstance(approval, dict)
    assert isinstance(plan_reconciled, dict)
    assert approval == {
        "schema_version": "krystal-quorum.approval.v1",
        "tool_version": "0.7.0",
        "created_at": approval["created_at"],
        "authenticity": "unsigned",
        "verdict": "APPROVE",
        "plan_path": "docs/plan.md",
        "plan_sha256": plan_sha256,
        "base_ref": "HEAD",
        "base_sha": baseline_sha,
        "reviewers_used": REVIEWERS,
        "reviewer_families": REVIEWER_FAMILIES,
        "diversity": "ok",
        "reconciled_sha256": _canonical_sha256(plan_reconciled),
        "commitments": EXPECTED_COMMITMENTS,
    }
    assert plan_reconciled["schema_version"] == "1.2"
    assert plan_reconciled["merged_verdict"] == "APPROVE"
    assert plan_reconciled["plan_sha256"] == plan_sha256
    assert plan_reconciled["reviewers_used"] == REVIEWERS
    assert plan_reconciled["round2_delta"] == 0
    assert plan_reconciled["unresolved_for_human"] == []
    assert (plan_run_dir / "plan_input.md").read_text(encoding="utf-8") == PLAN_TEXT
    assert (plan_run_dir / "plan_input.sha256").read_text(encoding="ascii").strip() == plan_sha256
    assert "Verdict: **APPROVE**" in (plan_run_dir / "summary.md").read_text(encoding="utf-8")
    _assert_reviewer_artifacts(plan_run_dir, clauses=PLAN_CLAUSES, diff_review=False)

    diff_result = _invoke_diff(golden)

    assert diff_result.exit_code == 0, diff_result.output
    result = json.loads(diff_result.stdout)
    assert set(result) == {
        "schema_version",
        "review_kind",
        "verdict",
        "plan_provenance",
        "plan",
        "git",
        "diff",
        "review_input_sha256",
        "quorum",
        "reviewers_used",
        "coverage",
        "scope_findings",
        "unresolved_for_human",
        "output_dir",
    }
    diff_run_dir = Path(result["output_dir"])
    approval_sha256 = _canonical_sha256(approval)
    assert result["schema_version"] == "krystal-quorum.diff.v1"
    assert result["review_kind"] == "diff"
    assert result["verdict"] == "APPROVE"
    assert result["plan_provenance"] == "verified_receipt"
    assert result["plan"] == {
        "path": "docs/plan.md",
        "sha256": plan_sha256,
        "approval_sha256": approval_sha256,
    }
    assert result["git"] == {
        "base_ref": "HEAD",
        "base_sha": baseline_sha,
        "head_ref": implementation_sha,
        "head_sha": implementation_sha,
        "merge_base_sha": None,
        "working_tree": False,
    }
    assert result["diff"]["changed_files"] == [
        {"status": "M", "path": "src/feature.py", "old_path": None}
    ]
    assert result["quorum"] == {
        "health": "healthy",
        "usable_reviewers": 2,
        "total_reviewers": 2,
        "distinct_families": 2,
        "agreement_ratio": 1.0,
        "contradiction_count": 0,
    }
    assert result["reviewers_used"] == REVIEWERS
    assert result["coverage"] == [
        {
            "commitment_id": item["id"],
            "status": "IMPLEMENTED",
            "corroborated": True,
            "reviewers": REVIEWERS,
            "evidence": ["src/feature.py:1"],
        }
        for item in EXPECTED_COMMITMENTS
    ]
    assert result["scope_findings"] == []
    assert result["unresolved_for_human"] == []
    assert diff_run_dir.parent == out_dir
    assert diff_run_dir != plan_run_dir

    patch = (diff_run_dir / "diff_input.patch").read_text(encoding="utf-8")
    assert patch == golden.expected_patch
    assert "### krystal-quorum diff: committed" in patch
    assert 'return "pending"' in patch
    assert 'return "ready"' in patch
    assert result["diff"]["sha256"] == hashlib.sha256(patch.encode("utf-8")).hexdigest()
    assert (diff_run_dir / "diff_input.sha256").read_text(encoding="ascii").strip() == result[
        "diff"
    ]["sha256"]
    assert _load_json(diff_run_dir / "changed_files.json") == [
        {
            "status": "M",
            "path": "src/feature.py",
            "old_path": None,
            "kind": "text",
            "source": "committed",
        }
    ]

    review_input_text = (diff_run_dir / "review_input.md").read_text(encoding="utf-8")
    review_input = json.loads(review_input_text)
    assert result["review_input_sha256"] == hashlib.sha256(
        review_input_text.encode("utf-8")
    ).hexdigest()
    assert (diff_run_dir / "review_input.sha256").read_text(encoding="ascii").strip() == result[
        "review_input_sha256"
    ]
    assert review_input["review_kind"] == "diff"
    assert review_input["plan"] == {
        "path": "docs/plan.md",
        "sha256": plan_sha256,
        "approval_sha256": approval_sha256,
        "provenance": "verified_receipt",
        "text": PLAN_TEXT,
    }
    assert review_input["commitments"] == [
        {**item, "group": None} for item in EXPECTED_COMMITMENTS
    ]
    assert review_input["git"] == {
        "base_ref": baseline_sha,
        "base_sha": baseline_sha,
        "head_ref": implementation_sha,
        "head_sha": implementation_sha,
        "merge_base_sha": None,
        "comparison": "committed",
        "include_untracked": True,
        "working_tree_status": [],
    }
    assert review_input["changed_files"] == _load_json(diff_run_dir / "changed_files.json")
    assert review_input["patch"] == patch

    assert _load_json(diff_run_dir / "approval.json") == approval
    assert _load_json(diff_run_dir / "coverage.json") == result["coverage"]
    assert _load_json(diff_run_dir / "reconciled.json") == result
    assert (diff_run_dir / "plan_input.md").read_text(encoding="utf-8") == PLAN_TEXT
    assert (diff_run_dir / "plan_input.sha256").read_text(encoding="ascii").strip() == plan_sha256
    _assert_reviewer_artifacts(diff_run_dir, clauses=DIFF_CLAUSES, diff_review=True)

    manifest = _load_json(diff_run_dir / "manifest.json")
    assert isinstance(manifest, dict)
    assert manifest["schema_version"] == "krystal-quorum.diff.v1"
    assert manifest["tool_version"] == "0.7.0"
    assert manifest["plan_provenance"] == "verified_receipt"
    assert manifest["plan"] == result["plan"]
    assert manifest["git"] == result["git"]
    assert manifest["diff"] == result["diff"]
    assert manifest["review_input_sha256"] == result["review_input_sha256"]
    assert manifest["reviewers_used"] == REVIEWERS
    assert manifest["reviewer_families"] == REVIEWER_FAMILIES
    assert manifest["data_boundaries"] == {reviewer: "local" for reviewer in REVIEWERS}

    artifact_hashes = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
    assert len(artifact_hashes) == len(manifest["artifacts"])
    assert set(artifact_hashes) == {
        path.relative_to(diff_run_dir).as_posix()
        for path in diff_run_dir.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert len([path for path in artifact_hashes if path.startswith("round1/")]) == 2
    assert len([path for path in artifact_hashes if path.startswith("round2/")]) == 2
    for relative_path, expected_hash in artifact_hashes.items():
        artifact = diff_run_dir / relative_path
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_hash

    summary = (diff_run_dir / "summary.md").read_text(encoding="utf-8")
    assert "Verdict: **APPROVE**" in summary
    assert "Plan provenance: `verified_receipt`" in summary
    assert "Health: `healthy`" in summary
    assert "Usable reviewers: `2` of `2`" in summary
    assert "No unresolved items." in summary
    for commitment in EXPECTED_COMMITMENTS:
        assert f"| {commitment['id']} | IMPLEMENTED | yes | src/feature.py:1 |" in summary
