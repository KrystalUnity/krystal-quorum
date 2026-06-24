from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_ROOT.parent


def _load_expected() -> dict[str, Any]:
    return json.loads((BENCHMARK_ROOT / "expected-findings.json").read_text(encoding="utf-8"))


def _parse_cli_json(stdout: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def run_fixture(
    *,
    fixture: dict[str, Any],
    reviewers: str,
    config: str | None,
    round2: bool,
    require_diversity: bool,
) -> dict[str, Any]:
    plan_path = BENCHMARK_ROOT / "fixtures" / fixture["path"]
    command = [
        sys.executable,
        "-m",
        "krystal_quorum",
        "review",
        str(plan_path),
        "--reviewers",
        reviewers,
        "--out-dir",
        str(REPO_ROOT / ".krystal-quorum" / "benchmark-runs"),
    ]
    if config:
        command.extend(["--config", config])
    if round2:
        command.append("--round2")
    if require_diversity:
        command.append("--require-diversity")

    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "fixture": fixture["path"],
        "description": fixture["description"],
        "expected_topics": fixture["expected_topics"],
        "reviewers": reviewers,
        "round2": round2,
        "require_diversity": require_diversity,
        "exit_code": completed.returncode,
        "stdout_json": _parse_cli_json(completed.stdout),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Krystal Quorum benchmark fixtures.")
    parser.add_argument("--reviewers", required=True, help="Comma-separated reviewer list.")
    parser.add_argument("--config", help="Optional reviewer TOML config.")
    parser.add_argument("--round2", action="store_true", help="Run round 2 cross-audit.")
    parser.add_argument(
        "--require-diversity",
        action="store_true",
        help="Fail runs whose reviewer families are too similar.",
    )
    parser.add_argument("--out", required=True, help="JSONL output path.")
    args = parser.parse_args()

    expected = _load_expected()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for fixture in expected["fixtures"]:
            row = run_fixture(
                fixture=fixture,
                reviewers=args.reviewers,
                config=args.config,
                round2=args.round2,
                require_diversity=args.require_diversity,
            )
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
