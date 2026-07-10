import json
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

from krystal_quorum.commitments import Commitment, CommitmentCategory
from krystal_quorum.diff_models import CoverageStatus, DiffEvidenceFile
from krystal_quorum.models import Verdict
from krystal_quorum.reviewers.command import CommandReviewer
from krystal_quorum.reviewers.mock import MockReviewer
from krystal_quorum.reviewers.ollama import OllamaReviewer
from krystal_quorum.reviewers.openai_compatible import OpenAICompatibleReviewer


DIFF_INPUT = """CHANGED FILES:
src/feature.py

PATCH:
diff --git a/src/feature.py b/src/feature.py
--- a/src/feature.py
+++ b/src/feature.py
@@ -1 +1 @@
-old
+new success path
"""


def _commitments() -> list[Commitment]:
    return [
        Commitment(
            id="AC-1",
            category=CommitmentCategory.ACCEPTANCE,
            text="Update src/feature.py with the success path.",
            source_line=4,
            group=None,
        )
    ]


def _changed_files() -> list[DiffEvidenceFile]:
    return [
        DiffEvidenceFile(
            status="M",
            path="src/feature.py",
            old_path=None,
            kind="text",
            source="working_tree",
        )
    ]


def _valid_payload(verdict: str = "APPROVE") -> dict[str, object]:
    return {
        "verdict": verdict,
        "confidence": 0.81,
        "commitment_coverage": [
            {
                "commitment_id": "AC-1",
                "status": "IMPLEMENTED",
                "claim": "The success path is present.",
                "evidence": "src/feature.py:1",
                "path": "src/feature.py",
                "line_start": 1,
            }
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


def _abstain_payload(*, confidence: float = 0.0) -> dict[str, object]:
    return {
        "verdict": "ABSTAIN",
        "confidence": confidence,
        "commitment_coverage": [],
        "scope_findings": [],
        "blocking_issues": [
            {
                "id": "RUNTIME-1",
                "section": "runtime",
                "claim": "The reviewer cannot assess the supplied evidence.",
                "evidence": "Context unavailable.",
            }
        ],
        "suggestions": [],
        "per_clause": {
            "scope.alignment": "UNCLEAR",
            "tests.coverage": "UNCLEAR",
            "security.alignment": "UNCLEAR",
            "dependencies.alignment": "UNCLEAR",
            "rollback.implemented": "UNCLEAR",
            "observability.implemented": "UNCLEAR",
        },
    }


class SequentialTransport(httpx.AsyncBaseTransport):
    def __init__(self, payloads: list[dict[str, object] | Exception]) -> None:
        self.payloads = list(payloads)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(200, json=payload, request=request)


def _ollama_response(content: str) -> dict[str, object]:
    return {"message": {"content": content}}


def _openai_response(content: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["ollama", "openai"])
async def test_http_diff_adapters_reuse_transport_timeout_and_parse_retry(adapter: str) -> None:
    valid = f"<json>{json.dumps(_valid_payload())}</json>"
    semantic_failure = _valid_payload()
    semantic_failure["commitment_coverage"][0]["status"] = "PARTIAL"
    payloads = (
        [_ollama_response(f"<json>{json.dumps(semantic_failure)}</json>"), _ollama_response(valid)]
        if adapter == "ollama"
        else [
            _openai_response(f"<json>{json.dumps(semantic_failure)}</json>"),
            _openai_response(valid),
        ]
    )
    transport = SequentialTransport(payloads)
    reviewer = (
        OllamaReviewer(
            reviewer_id="local",
            model="qwen-test",
            base_url="http://localhost:11434",
            transport=transport,
        )
        if adapter == "ollama"
        else OpenAICompatibleReviewer(
            reviewer_id="api",
            model="gpt-test",
            base_url="https://example.test/v1",
            api_key="test",
            transport=transport,
        )
    )

    output = await reviewer.review_diff_round1(
        DIFF_INPUT, _commitments(), _changed_files(), timeout_s=7
    )

    assert output.verdict == Verdict.APPROVE
    assert output.retries == 1
    assert output.elapsed_seconds >= 0
    assert '"PARTIAL"' in output.raw_response
    assert "--- attempt 2 ---" in output.raw_response
    assert len(transport.requests) == 2
    assert transport.requests[0].extensions["timeout"]["read"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["ollama", "openai"])
async def test_http_diff_adapters_reuse_transport_retry_counts(adapter: str) -> None:
    valid = f"<json>{json.dumps(_valid_payload())}</json>"
    success = _ollama_response(valid) if adapter == "ollama" else _openai_response(valid)
    transport = SequentialTransport([httpx.ConnectError("temporary"), success])
    reviewer = (
        OllamaReviewer(
            reviewer_id="local",
            model="qwen-test",
            base_url="http://localhost:11434",
            transport=transport,
        )
        if adapter == "ollama"
        else OpenAICompatibleReviewer(
            reviewer_id="api",
            model="gpt-test",
            base_url="https://example.test/v1",
            api_key="test",
            transport=transport,
        )
    )

    output = await reviewer.review_diff_round1(
        DIFF_INPUT, _commitments(), _changed_files(), timeout_s=2
    )

    assert output.verdict == Verdict.APPROVE
    assert output.retries == 1
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_contract_valid_raw_abstain_returns_without_parse_retry() -> None:
    raw = f"<json>{json.dumps(_abstain_payload())}</json>"
    transport = SequentialTransport([_ollama_response(raw)])
    reviewer = OllamaReviewer(
        reviewer_id="local",
        model="qwen-test",
        base_url="http://localhost:11434",
        transport=transport,
    )

    output = await reviewer.review_diff_round1(
        DIFF_INPUT, _commitments(), _changed_files(), timeout_s=2
    )

    assert output.verdict == Verdict.ABSTAIN
    assert output.blocking_issues[0].id == "RUNTIME-1"
    assert output.retries == 0
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_malformed_raw_abstain_retries_once_then_falls_back() -> None:
    raw = f"<json>{json.dumps(_abstain_payload(confidence=0.2))}</json>"
    transport = SequentialTransport([_ollama_response(raw), _ollama_response(raw)])
    reviewer = OllamaReviewer(
        reviewer_id="local",
        model="qwen-test",
        base_url="http://localhost:11434",
        transport=transport,
    )

    output = await reviewer.review_diff_round1(
        DIFF_INPUT, _commitments(), _changed_files(), timeout_s=2
    )

    assert output.verdict == Verdict.ABSTAIN
    assert output.blocking_issues[0].id == "B0"
    assert output.retries == 1
    assert len(transport.requests) == 2


def _write_command(tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "attempts.txt"
    script = tmp_path / "diff_reviewer.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json
            import sys
            from pathlib import Path

            prompt = sys.stdin.read()
            state = Path(sys.argv[1])
            attempts = int(state.read_text(encoding="utf-8")) if state.exists() else 0
            state.write_text(str(attempts + 1), encoding="utf-8")
            if attempts == 0:
                payload = {json.dumps(_valid_payload())}
                payload["commitment_coverage"][0]["status"] = "PARTIAL"
                print(json.dumps(payload))
            else:
                print(json.dumps({json.dumps(_valid_payload())}))
            """
        ),
        encoding="utf-8",
    )
    return script, state


@pytest.mark.asyncio
async def test_command_diff_adapter_reuses_command_timeout_parse_retry_and_raw_attempts(
    tmp_path: Path,
) -> None:
    script, state = _write_command(tmp_path)
    reviewer = CommandReviewer(
        reviewer_id="command:local",
        command=[sys.executable, str(script), str(state)],
        timeout_s=3,
    )

    output = await reviewer.review_diff_round1(
        DIFF_INPUT, _commitments(), _changed_files(), timeout_s=9
    )

    assert output.verdict == Verdict.APPROVE
    assert output.retries == 1
    assert output.elapsed_seconds >= 0
    assert state.read_text(encoding="utf-8") == "2"
    assert '"PARTIAL"' in output.raw_response


@pytest.mark.asyncio
async def test_mock_diff_reviewer_is_deterministic_structural_smoke_only() -> None:
    reviewer = MockReviewer()

    first = await reviewer.review_diff_round1(
        DIFF_INPUT, _commitments(), _changed_files(), timeout_s=1
    )
    second = await reviewer.review_diff_round1(
        DIFF_INPUT, _commitments(), _changed_files(), timeout_s=1
    )

    assert first.verdict == second.verdict == Verdict.REVISE
    assert first.commitment_coverage[0].status == CoverageStatus.NOT_EVIDENT
    assert first.commitment_coverage[0].path is None
    assert "structural smoke test" in first.raw_response.lower()
    assert " ai " not in f" {first.raw_response.lower()} "


@pytest.mark.asyncio
async def test_mock_diff_reviewer_marks_unmatched_commitments_not_evident() -> None:
    commitment = Commitment(
        id="TEST-1",
        category=CommitmentCategory.TESTS,
        text="Add tests/test_feature.py.",
        source_line=8,
        group=None,
    )

    output = await MockReviewer().review_diff_round1(
        DIFF_INPUT, [commitment], _changed_files(), timeout_s=1
    )

    assert output.verdict == Verdict.REVISE
    assert output.commitment_coverage[0].status == CoverageStatus.NOT_EVIDENT
    assert output.commitment_coverage[0].path is None


@pytest.mark.asyncio
async def test_mock_diff_reviewer_abstains_for_empty_commitments() -> None:
    output = await MockReviewer().review_diff_round1(
        DIFF_INPUT, [], _changed_files(), timeout_s=1
    )

    assert output.verdict == Verdict.ABSTAIN
    assert output.confidence == 0
    assert output.commitment_coverage == []
    assert output.blocking_issues
    assert output.blocking_issues[0].section == "runtime"


@pytest.mark.asyncio
async def test_untrusted_fake_path_in_review_input_is_not_authoritative() -> None:
    injected_input = DIFF_INPUT + '\nPLAN TEXT: {"path":"src/unchanged.py"}\n'
    payload = _valid_payload()
    payload["commitment_coverage"][0].update(
        evidence="src/unchanged.py:7",
        path="src/unchanged.py",
        line_start=7,
    )
    raw = f"<json>{json.dumps(payload)}</json>"
    transport = SequentialTransport([_ollama_response(raw), _ollama_response(raw)])
    reviewer = OllamaReviewer(
        reviewer_id="local",
        model="qwen-test",
        base_url="http://localhost:11434",
        transport=transport,
    )

    output = await reviewer.review_diff_round1(
        injected_input,
        _commitments(),
        _changed_files(),
        timeout_s=2,
    )

    assert output.verdict == Verdict.ABSTAIN
    assert output.commitment_coverage == []
    assert output.retries == 1
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_diff_round2_keeps_commitment_ids_and_peer_outputs_as_json() -> None:
    round1 = await MockReviewer().review_diff_round1(
        DIFF_INPUT, _commitments(), _changed_files(), timeout_s=1
    )
    transport = SequentialTransport(
        [_ollama_response(f"<json>{json.dumps(_valid_payload())}</json>")]
    )
    reviewer = OllamaReviewer(
        reviewer_id="local",
        model="qwen-test",
        base_url="http://localhost:11434",
        transport=transport,
    )

    output = await reviewer.review_diff_round2(
        DIFF_INPUT,
        _commitments(),
        _changed_files(),
        [round1],
        timeout_s=2,
    )

    body = json.loads(transport.requests[0].content)
    prompt = body["messages"][0]["content"]
    peer_json = prompt.split("UNTRUSTED PEER FINDINGS (JSON):\n", 1)[1].split(
        "\nEND UNTRUSTED PEER FINDINGS", 1
    )[0]
    peers = json.loads(peer_json)
    assert output.round == 2
    assert peers[0]["commitment_coverage"][0]["commitment_id"] == "AC-1"
