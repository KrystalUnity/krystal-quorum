from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Pattern


@dataclass(frozen=True)
class SensitiveFinding:
    warning_class: str
    _start: int = field(repr=False)
    _end: int = field(repr=False)


_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    ("private-key-block", re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bx(?:ox(?:a|b|p|r|s)|app)-[A-Za-z0-9-]{20,}\b")),
    ("openai-style-secret", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    (
        "bearer-authorization",
        re.compile(
            r"^[ +\-]?\s*authorization\s*:\s*bearer\s+[A-Za-z0-9._~+/-]{20,}\b",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"^[ +\-]?\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*"
    r"(?:API_KEY|SECRET|TOKEN|PASSWORD)[A-Za-z0-9_]*)\s*(?:=|:)\s*(?P<value>[^\r\n#]+)",
    re.IGNORECASE | re.MULTILINE,
)


def scan_sensitive_input(text: str) -> list[SensitiveFinding]:
    findings = [
        SensitiveFinding(warning_class, match.start(), match.end())
        for warning_class, pattern in _PATTERNS
        for match in pattern.finditer(text)
    ]
    findings.extend(_assignment_findings(text))
    return sorted(findings, key=lambda finding: (finding._start, finding.warning_class))


def summarize_sensitive_findings(findings: list[SensitiveFinding]) -> dict[str, int]:
    counts = Counter(finding.warning_class for finding in findings)
    return {warning_class: counts[warning_class] for warning_class in sorted(counts)}


def _assignment_findings(text: str) -> list[SensitiveFinding]:
    findings: list[SensitiveFinding] = []
    for match in _SENSITIVE_ASSIGNMENT.finditer(text):
        if _looks_like_assigned_secret(match.group("value")):
            findings.append(SensitiveFinding("sensitive-assignment", match.start(), match.end()))
    return findings


def _looks_like_assigned_secret(value: str) -> bool:
    candidate = value.strip().strip("'\"")
    if len(candidate) < 12:
        return False
    if (candidate.startswith("<") and candidate.endswith(">")) or (
        candidate.startswith("${") and candidate.endswith("}")
    ):
        return False
    return not any(label in candidate.lower() for label in ("your-", "your_", "your "))
