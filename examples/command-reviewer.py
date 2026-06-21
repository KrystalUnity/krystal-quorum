from __future__ import annotations

import json
import sys


def main() -> None:
    prompt = sys.stdin.read()
    plan_text = prompt.rsplit("PLAN:", 1)[-1]
    has_acceptance = "acceptance" in plan_text.lower()
    issues = []
    if not has_acceptance:
        issues.append(
            {
                "id": "B1",
                "section": "Acceptance",
                "claim": "The plan does not include explicit acceptance criteria.",
                "evidence": "The review prompt did not include an acceptance section.",
            }
        )

    print(
        json.dumps(
            {
                "verdict": "APPROVE" if not issues else "REVISE",
                "confidence": 0.75,
                "blocking_issues": issues,
                "suggestions": [],
                "per_clause": {},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
