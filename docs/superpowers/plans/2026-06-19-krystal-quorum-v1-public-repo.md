# Krystal Quorum V1 Public Repo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clean public Krystal Quorum repo that provides a real local CLI for multi-reviewer preflight review of AI coding plans.

**Architecture:** The CLI reads a markdown plan, dispatches configured reviewers through a small provider interface, reconciles strict reviewer JSON into a human-triage result, and persists every run in an append-only output directory. Integrations are thin wrappers around the same CLI.

**Tech Stack:** Python 3.11+, Typer, Pydantic v2, httpx, pytest, Ruff, TOML config, GitHub Actions metadata.

---

## File Structure

- Create: `README.md` - public positioning, quickstart, install, examples.
- Create: `pyproject.toml` - package metadata, dependencies, console script, tool config.
- Create: `src/krystal_quorum/__init__.py` - package version.
- Create: `src/krystal_quorum/__main__.py` - `python -m krystal_quorum` entrypoint.
- Create: `src/krystal_quorum/cli.py` - Typer CLI and exit-code mapping.
- Create: `src/krystal_quorum/config.py` - TOML config loading and reviewer config parsing.
- Create: `src/krystal_quorum/models.py` - Pydantic models and enums.
- Create: `src/krystal_quorum/prompts.py` - reviewer prompts.
- Create: `src/krystal_quorum/reconcile.py` - verdict reconciliation.
- Create: `src/krystal_quorum/persist.py` - append-only run directory writes.
- Create: `src/krystal_quorum/reviewers/base.py` - reviewer protocol and JSON parsing.
- Create: `src/krystal_quorum/reviewers/mock.py` - deterministic no-key reviewer.
- Create: `src/krystal_quorum/reviewers/ollama.py` - local Ollama adapter.
- Create: `src/krystal_quorum/reviewers/openai_compatible.py` - BYOK OpenAI-compatible adapter.
- Create: `examples/bad-plan.md` - safe synthetic example.
- Create: `integrations/github-action/action.yml` - thin GitHub Action wrapper.
- Create: `integrations/github-action/README.md` - action usage.
- Create: `integrations/hermes-skill/SKILL.md` - generic skill instructions.
- Create: `integrations/openclaw-skill/SKILL.md` - generic skill instructions.
- Create: `tests/test_models.py` - schema tests.
- Create: `tests/test_reconcile.py` - reconciler tests.
- Create: `tests/test_persist.py` - output persistence tests.
- Create: `tests/test_cli.py` - CLI exit-code tests.
- Create: `tests/test_mock_review.py` - mock reviewer tests.

## Task 1: Repo Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/krystal_quorum/__init__.py`
- Create: `src/krystal_quorum/__main__.py`
- Create: `src/krystal_quorum/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI smoke test**

```python
from typer.testing import CliRunner

from krystal_quorum.cli import app


def test_cli_help_runs():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "review" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_cli_help_runs -q`

Expected: fails because `krystal_quorum` package does not exist.

- [ ] **Step 3: Add package metadata and CLI skeleton**

`pyproject.toml`:

```toml
[project]
name = "krystal-quorum"
version = "0.1.0"
description = "Preflight review for AI coding plans."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.7",
  "typer>=0.12",
]

[project.scripts]
krystal-quorum = "krystal_quorum.cli:main"

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "ruff>=0.5",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

`src/krystal_quorum/__init__.py`:

```python
__version__ = "0.1.0"
```

`src/krystal_quorum/__main__.py`:

```python
from .cli import main


if __name__ == "__main__":
    main()
```

`src/krystal_quorum/cli.py`:

```python
from __future__ import annotations

import typer

app = typer.Typer(help="Preflight review for AI coding plans.")


@app.command()
def review(plan: str) -> None:
    """Review a markdown coding plan."""
    typer.echo(f"Krystal Quorum review requested for {plan}")


def main() -> None:
    app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::test_cli_help_runs -q`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests
git commit -m "chore: scaffold krystal quorum package"
```

## Task 2: Strict Models

**Files:**
- Create: `src/krystal_quorum/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing schema tests**

```python
import pytest
from pydantic import ValidationError

from krystal_quorum.models import ClauseStatus, ReviewerOutput, Verdict


def test_reviewer_output_accepts_valid_payload():
    output = ReviewerOutput(
        reviewer="mock",
        round=1,
        verdict=Verdict.REVISE,
        confidence=0.75,
        blocking_issues=[],
        suggestions=[],
        per_clause={"acceptance.1": ClauseStatus.UNSATISFIED},
        raw_response="{}",
        elapsed_seconds=0.1,
    )

    assert output.verdict == Verdict.REVISE


def test_reviewer_output_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ReviewerOutput(
            reviewer="mock",
            round=1,
            verdict="APPROVE",
            confidence=0.5,
            blocking_issues=[],
            suggestions=[],
            per_clause={},
            raw_response="{}",
            elapsed_seconds=0.1,
            unexpected=True,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -q`

Expected: fails because `krystal_quorum.models` does not exist.

- [ ] **Step 3: Add strict Pydantic models**

```python
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Verdict(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    BLOCK = "BLOCK"
    ABSTAIN = "ABSTAIN"


class ClauseStatus(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    NA = "N/A"
    UNCLEAR = "UNCLEAR"


class ReviewIssue(StrictModel):
    id: str
    section: str
    claim: str
    evidence: str


class ReviewSuggestion(StrictModel):
    id: str
    section: str
    claim: str
    rationale: str


class ReviewerOutput(StrictModel):
    reviewer: str
    round: Literal[1, 2]
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    blocking_issues: list[ReviewIssue]
    suggestions: list[ReviewSuggestion]
    per_clause: dict[str, ClauseStatus]
    raw_response: str
    elapsed_seconds: float
    retries: int = 0


class ContradictionFinding(StrictModel):
    clause_id: str
    reviewer_positions: dict[str, ClauseStatus]
    severity: Literal["high", "medium", "low"]


class ReconciledVerdict(StrictModel):
    plan_path: str
    plan_sha256: str
    timestamp: str
    reviewers_used: list[str]
    abstained_reviewers: list[str]
    merged_verdict: Verdict
    confidence: float
    consensus_blocking_issues: list[ReviewIssue]
    singleton_blocking_issues: list[ReviewIssue]
    contradictions: list[ContradictionFinding]
    unresolved_for_human: list[str]
    round1_outputs: list[ReviewerOutput]
    round2_outputs: list[ReviewerOutput]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -q`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/krystal_quorum/models.py tests/test_models.py
git commit -m "feat: add strict review models"
```

## Task 3: Reviewer JSON Parsing and Mock Reviewer

**Files:**
- Create: `src/krystal_quorum/reviewers/__init__.py`
- Create: `src/krystal_quorum/reviewers/base.py`
- Create: `src/krystal_quorum/reviewers/mock.py`
- Create: `tests/test_mock_review.py`

- [ ] **Step 1: Write failing mock reviewer tests**

```python
import pytest

from krystal_quorum.models import Verdict
from krystal_quorum.reviewers.base import parse_reviewer_output
from krystal_quorum.reviewers.mock import MockReviewer


def test_parse_reviewer_json_from_tags():
    raw = '<json>{"verdict":"APPROVE","confidence":0.9,"blocking_issues":[],"suggestions":[],"per_clause":{}}</json>'

    output = parse_reviewer_output("mock", 1, raw, elapsed_seconds=0.2, retries=0)

    assert output.verdict == Verdict.APPROVE


def test_unparseable_output_abstains():
    output = parse_reviewer_output("mock", 1, "not json", elapsed_seconds=0.1, retries=0)

    assert output.verdict == Verdict.ABSTAIN
    assert output.blocking_issues[0].id == "B0"


@pytest.mark.asyncio
async def test_mock_reviewer_flags_missing_acceptance():
    reviewer = MockReviewer()

    output = await reviewer.review_round1("Build a CLI with no acceptance section.", timeout_s=1)

    assert output.verdict == Verdict.REVISE
    assert output.blocking_issues
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mock_review.py -q`

Expected: fails because reviewer modules do not exist.

- [ ] **Step 3: Implement parser and mock reviewer**

`src/krystal_quorum/reviewers/base.py`:

```python
from __future__ import annotations

import json
import re
import time
from typing import Any, Protocol

from pydantic import ValidationError

from krystal_quorum.models import ReviewIssue, ReviewerOutput, Verdict


class ReviewerProtocol(Protocol):
    id: str

    async def review_round1(self, plan_text: str, *, timeout_s: int) -> ReviewerOutput: ...

    async def review_round2(
        self, plan_text: str, round1_outputs: list[ReviewerOutput], *, timeout_s: int
    ) -> ReviewerOutput: ...


def fallback_output(
    reviewer: str,
    round_number: int,
    claim: str,
    evidence: str = "",
    raw_response: str = "",
    elapsed_seconds: float = 0.0,
    retries: int = 0,
) -> ReviewerOutput:
    return ReviewerOutput(
        reviewer=reviewer,
        round=round_number,  # type: ignore[arg-type]
        verdict=Verdict.ABSTAIN,
        confidence=0.0,
        blocking_issues=[
            ReviewIssue(
                id="B0",
                section="runtime",
                claim=f"reviewer abstained: {claim}",
                evidence=evidence[:500],
            )
        ],
        suggestions=[],
        per_clause={},
        raw_response=raw_response,
        elapsed_seconds=elapsed_seconds,
        retries=retries,
    )


def extract_json(raw: str) -> dict[str, Any] | None:
    match = re.search(r"<json>\\s*(\\{.*?\\})\\s*</json>", raw, flags=re.DOTALL | re.IGNORECASE)
    candidate = match.group(1) if match else raw.strip()
    if not candidate.startswith("{"):
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_reviewer_output(
    reviewer: str,
    round_number: int,
    raw_response: str,
    elapsed_seconds: float,
    retries: int,
) -> ReviewerOutput:
    try:
        payload = extract_json(raw_response)
        if payload is None:
            raise ValueError("reviewer output unparseable")
        payload.update(
            {
                "reviewer": reviewer,
                "round": round_number,
                "raw_response": raw_response,
                "elapsed_seconds": elapsed_seconds,
                "retries": retries,
            }
        )
        return ReviewerOutput.model_validate(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        return fallback_output(
            reviewer,
            round_number,
            claim="reviewer output unparseable",
            evidence=raw_response[:500] or str(exc),
            raw_response=raw_response,
            elapsed_seconds=elapsed_seconds,
            retries=retries,
        )


def elapsed_since(start: float) -> float:
    return round(time.monotonic() - start, 3)
```

`src/krystal_quorum/reviewers/mock.py`:

```python
from __future__ import annotations

import time

from krystal_quorum.models import ClauseStatus, ReviewIssue, ReviewerOutput, Verdict
from krystal_quorum.reviewers.base import elapsed_since


class MockReviewer:
    id = "mock"

    async def review_round1(self, plan_text: str, *, timeout_s: int) -> ReviewerOutput:
        del timeout_s
        start = time.monotonic()
        lower = plan_text.lower()
        has_acceptance = "acceptance" in lower
        issues = []
        if not has_acceptance:
            issues.append(
                ReviewIssue(
                    id="B1",
                    section="Acceptance",
                    claim="The plan does not include explicit acceptance criteria.",
                    evidence="No heading or paragraph containing 'acceptance' was found.",
                )
            )
        return ReviewerOutput(
            reviewer=self.id,
            round=1,
            verdict=Verdict.APPROVE if not issues else Verdict.REVISE,
            confidence=0.9,
            blocking_issues=issues,
            suggestions=[],
            per_clause={"acceptance.1": ClauseStatus.SATISFIED if has_acceptance else ClauseStatus.UNSATISFIED},
            raw_response="mock deterministic review",
            elapsed_seconds=elapsed_since(start),
        )

    async def review_round2(self, plan_text: str, round1_outputs: list[ReviewerOutput], *, timeout_s: int) -> ReviewerOutput:
        del round1_outputs
        return await self.review_round1(plan_text, timeout_s=timeout_s)
```

`src/krystal_quorum/reviewers/__init__.py`:

```python
from .mock import MockReviewer

__all__ = ["MockReviewer"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mock_review.py -q`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/krystal_quorum/reviewers tests/test_mock_review.py
git commit -m "feat: add reviewer parser and mock reviewer"
```

## Task 4: Reconciler and Persistence

**Files:**
- Create: `src/krystal_quorum/reconcile.py`
- Create: `src/krystal_quorum/persist.py`
- Create: `tests/test_reconcile.py`
- Create: `tests/test_persist.py`

- [ ] **Step 1: Write failing reconciler and persistence tests**

```python
from pathlib import Path

from krystal_quorum.models import ClauseStatus, ReviewIssue, ReviewerOutput, Verdict
from krystal_quorum.persist import persist_run, plan_sha256
from krystal_quorum.reconcile import reconcile


def output(reviewer: str, verdict: Verdict, issue: ReviewIssue | None = None) -> ReviewerOutput:
    return ReviewerOutput(
        reviewer=reviewer,
        round=1,
        verdict=verdict,
        confidence=0.8,
        blocking_issues=[issue] if issue else [],
        suggestions=[],
        per_clause={"acceptance.1": ClauseStatus.UNSATISFIED if issue else ClauseStatus.SATISFIED},
        raw_response="{}",
        elapsed_seconds=0.1,
    )


def test_reconcile_rejects_consensus_blocker():
    issue = ReviewIssue(id="B1", section="Acceptance", claim="Missing exit codes", evidence="none")

    result = reconcile(
        plan_path="plan.md",
        plan_text="plan",
        reviewers_used=["a", "b"],
        round1_outputs=[output("a", Verdict.BLOCK, issue), output("b", Verdict.BLOCK, issue)],
        round2_outputs=[],
    )

    assert result.merged_verdict == Verdict.BLOCK
    assert len(result.consensus_blocking_issues) == 1


def test_persist_run_writes_expected_files(tmp_path: Path):
    result = reconcile(
        plan_path="plan.md",
        plan_text="## Acceptance\\n- Works",
        reviewers_used=["mock"],
        round1_outputs=[output("mock", Verdict.APPROVE)],
        round2_outputs=[],
    )

    run_dir = persist_run(tmp_path, Path("plan.md"), "## Acceptance\\n- Works", result)

    assert (run_dir / "plan_input.md").exists()
    assert (run_dir / "reconciled.json").exists()
    assert (run_dir / "summary.md").exists()
    assert (run_dir / "plan_input.sha256").read_text().strip() == plan_sha256("## Acceptance\\n- Works")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reconcile.py tests/test_persist.py -q`

Expected: fails because modules do not exist.

- [ ] **Step 3: Implement reconciler and persistence**

Implementation should group similar issue claims with normalized lowercase fingerprints, ignore `ABSTAIN` in confidence, produce `REVISE` for singleton blockers, and write append-only run folders named `<plan-stem>_<UTC timestamp>`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reconcile.py tests/test_persist.py -q`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/krystal_quorum/reconcile.py src/krystal_quorum/persist.py tests/test_reconcile.py tests/test_persist.py
git commit -m "feat: reconcile and persist review runs"
```

## Task 5: Wire CLI Review Command

**Files:**
- Modify: `src/krystal_quorum/cli.py`
- Create: `src/krystal_quorum/config.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI review test**

```python
from pathlib import Path

from typer.testing import CliRunner

from krystal_quorum.cli import app


def test_review_command_writes_output(tmp_path: Path):
    plan = tmp_path / "plan.md"
    plan.write_text("Build a CLI with no acceptance section.", encoding="utf-8")
    out_dir = tmp_path / "reviews"

    result = CliRunner().invoke(app, ["review", str(plan), "--reviewers", "mock", "--out-dir", str(out_dir)])

    assert result.exit_code == 1
    assert list(out_dir.glob("plan_*"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_review_command_writes_output -q`

Expected: fails because the command does not run reviewers.

- [ ] **Step 3: Implement CLI orchestration**

The `review` command should read the plan, build reviewers from comma-separated IDs, run Round 1, optionally run Round 2, reconcile, persist, print JSON summary, and exit using the mapped verdict code.

- [ ] **Step 4: Run CLI tests**

Run: `pytest tests/test_cli.py -q`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/krystal_quorum/cli.py src/krystal_quorum/config.py tests/test_cli.py
git commit -m "feat: wire review CLI"
```

## Task 6: Real Reviewer Adapters

**Files:**
- Create: `src/krystal_quorum/prompts.py`
- Create: `src/krystal_quorum/reviewers/ollama.py`
- Create: `src/krystal_quorum/reviewers/openai_compatible.py`
- Create: tests for request payload construction using mocked `httpx`.

- [ ] **Step 1: Write mocked adapter tests**

Tests should verify:

- Ollama posts to `/api/chat`.
- OpenAI-compatible posts to `/chat/completions`.
- Both read `content` and fallback `reasoning`.
- Both convert runtime failure into `ABSTAIN`.

- [ ] **Step 2: Implement prompts and adapters**

Use strict JSON prompt instructions, bounded timeouts, no streaming in V1, and no provider-specific credentials in logs.

- [ ] **Step 3: Run adapter tests**

Run: `pytest tests -q`

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add src/krystal_quorum/prompts.py src/krystal_quorum/reviewers/ollama.py src/krystal_quorum/reviewers/openai_compatible.py tests
git commit -m "feat: add ollama and openai-compatible reviewers"
```

## Task 7: Public Docs and Integrations

**Files:**
- Create: `README.md`
- Create: `examples/bad-plan.md`
- Create: `integrations/github-action/action.yml`
- Create: `integrations/github-action/README.md`
- Create: `integrations/hermes-skill/SKILL.md`
- Create: `integrations/openclaw-skill/SKILL.md`

- [ ] **Step 1: Write README**

README must lead with the problem and a 30-second quickstart:

```markdown
# Krystal Quorum

Review the plan before your AI coding agent creates the mess.

Krystal Quorum is a local CLI that reviews markdown implementation plans with one or more independent reviewers, then writes a reconciled human-triage summary.

## Quickstart

```bash
pipx install .
krystal-quorum review examples/bad-plan.md --reviewers mock
```
```

- [ ] **Step 2: Add GitHub Action wrapper**

`integrations/github-action/action.yml`:

```yaml
name: Krystal Quorum Review
description: Review a markdown AI coding plan with Krystal Quorum.
inputs:
  plan:
    description: Path to the markdown plan.
    required: true
  reviewers:
    description: Comma-separated reviewer list.
    required: false
    default: mock
runs:
  using: composite
  steps:
    - name: Install Krystal Quorum
      shell: bash
      run: python -m pip install .
    - name: Run Krystal Quorum
      shell: bash
      run: krystal-quorum review "${{ inputs.plan }}" --reviewers "${{ inputs.reviewers }}"
```

- [ ] **Step 3: Add generic Hermes/OpenClaw skill packs**

Each skill should instruct the agent to write a plan, run `krystal-quorum review`, treat results as advisory, revise material findings, and ask the operator before coding on `REVISE` or `BLOCK`.

- [ ] **Step 4: Run docs leakage scan**

Run: `rg -i -f .public-denylist README.md examples integrations src tests`

Expected: no private boundary terms. The `.public-denylist` file is operator-provided and must stay out of the public release if it contains private names.

- [ ] **Step 5: Commit**

```bash
git add README.md examples integrations
git commit -m "docs: add public quickstart and integrations"
```

## Task 8: Final Verification

**Files:**
- Modify as needed only for failures found during verification.

- [ ] **Step 1: Install locally**

Run: `python -m pip install -e ".[dev]"`

Expected: install succeeds and exposes `krystal-quorum`.

- [ ] **Step 2: Run full test suite**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Run lint**

Run: `ruff check .`

Expected: no lint failures.

- [ ] **Step 4: Run mock review example**

Run: `krystal-quorum review examples/bad-plan.md --reviewers mock --out-dir .krystal-quorum/reviews`

Expected: exit code `1`, output directory created, summary explains missing acceptance criteria.

- [ ] **Step 5: Run leakage scan**

Run: `rg -i -f .public-denylist .`

Expected: no private boundary terms. If generic credential wording appears in public docs, verify it contains no real value.

- [ ] **Step 6: Commit final fixes**

```bash
git add .
git commit -m "chore: verify public v1 repo"
```

## Self-Review

- Spec coverage: The plan covers local CLI, strict schemas, reviewer adapters, persistence, GitHub Action, Hermes/OpenClaw skill packs, tests, docs, and leakage scan.
- Placeholder scan: No placeholder tasks remain; Task 6 asks for specific adapter behaviors and tests.
- Type consistency: Verdict names are `APPROVE`, `REVISE`, `BLOCK`, `ABSTAIN` throughout.
- Scope check: The plan avoids private infrastructure, server paths, internal coordination systems, terminal/session operations, and product-specific examples.
