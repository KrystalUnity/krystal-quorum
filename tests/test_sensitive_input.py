from __future__ import annotations

import pytest

from krystal_quorum.sensitive_input import scan_sensitive_input, summarize_sensitive_findings


def test_scans_every_adr_warning_class_without_exposing_values() -> None:
    slack_token = "xoxb-" + "123456789012-123456789012-abcdefghijklmnopqrstuvwx"
    text = f"""\
-----BEGIN PRIVATE KEY-----
synthetic-key-material
-----END PRIVATE KEY-----
aws = AKIA1234567890ABCDEF
slack = {slack_token}
openai = sk-synthetic_openai_secret_value_1234567890
github = ghp_abcdefghijklmnopqrstuvwxyz1234567890
Authorization: Bearer synthetic-bearer-authorization-token-123456
DATABASE_PASSWORD = synthetic-password-value-123456
"""

    findings = scan_sensitive_input(text)

    assert summarize_sensitive_findings(findings) == {
        "aws-access-key": 1,
        "bearer-authorization": 1,
        "github-token": 1,
        "openai-style-secret": 1,
        "private-key-block": 1,
        "sensitive-assignment": 1,
        "slack-token": 1,
    }
    assert "synthetic" not in repr(findings)
    assert all(not hasattr(finding, "value") for finding in findings)


def test_ignores_short_dummy_values_placeholders_and_documentation_labels() -> None:
    text = """\
AKIA123
xoxb-short
sk-short
ghp_short
Authorization: Bearer <TOKEN>
Authorization: Bearer ${TOKEN}
API_KEY = <API_KEY>
PASSWORD = ${PASSWORD}
TOKEN: your-token-here
Use API_KEY, SECRET, TOKEN, or PASSWORD in your environment.
"""

    assert scan_sensitive_input(text) == []


@pytest.mark.parametrize("prefix", ["+", "-", " "])
def test_scans_unified_diff_prefixed_authorization_and_assignments(prefix: str) -> None:
    text = (
        f"{prefix}Authorization: Bearer synthetic-diff-bearer-token-123456\n"
        f"{prefix}OPENAI_API_KEY=synthetic-diff-assignment-token-123456\n"
    )

    findings = scan_sensitive_input(text)

    assert summarize_sensitive_findings(findings) == {
        "bearer-authorization": 1,
        "sensitive-assignment": 1,
    }
    assert "synthetic" not in repr(findings)


def test_scans_slack_app_level_token_and_ignores_near_miss() -> None:
    findings = scan_sensitive_input(
        "xapp-abcdefghijklmnopqrstuvwxyz123456\n"
        "xapp-short\n"
    )

    assert summarize_sensitive_findings(findings) == {"slack-token": 1}
