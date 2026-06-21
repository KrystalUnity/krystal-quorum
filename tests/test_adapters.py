import httpx
import pytest

from krystal_quorum.models import Verdict
from krystal_quorum.reviewers.ollama import OllamaReviewer
from krystal_quorum.reviewers.openai_compatible import OpenAICompatibleReviewer


class CaptureTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.payload, request=request)


class SequentialTransport(httpx.AsyncBaseTransport):
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = self.payloads.pop(0)
        return httpx.Response(200, json=payload, request=request)


@pytest.mark.asyncio
async def test_ollama_posts_to_api_chat_and_reads_content():
    transport = CaptureTransport(
        {
            "message": {
                "content": '<json>{"verdict":"APPROVE","confidence":0.9,"blocking_issues":[],"suggestions":[],"per_clause":{}}</json>'
            }
        }
    )
    reviewer = OllamaReviewer(
        reviewer_id="local",
        model="qwen2.5:14b",
        base_url="http://localhost:11434",
        transport=transport,
    )

    output = await reviewer.review_round1("## Acceptance\n- Works", timeout_s=1)

    assert output.verdict == Verdict.APPROVE
    assert transport.requests[0].url.path == "/api/chat"


@pytest.mark.asyncio
async def test_ollama_retries_once_when_response_is_malformed():
    transport = SequentialTransport(
        [
            {"message": {"content": "not json"}},
            {
                "message": {
                    "content": '<json>{"verdict":"APPROVE","confidence":0.9,"blocking_issues":[],"suggestions":[],"per_clause":{}}</json>'
                }
            },
        ]
    )
    reviewer = OllamaReviewer(
        reviewer_id="local",
        model="qwen2.5:14b",
        base_url="http://localhost:11434",
        transport=transport,
    )

    output = await reviewer.review_round1("plan", timeout_s=1)

    assert output.verdict == Verdict.APPROVE
    assert output.retries == 1
    assert len(transport.requests) == 2
    assert "not json" in output.raw_response


@pytest.mark.asyncio
async def test_openai_compatible_posts_to_chat_completions_and_reads_reasoning():
    transport = CaptureTransport(
        {
            "choices": [
                {
                    "message": {
                        "reasoning": '<json>{"verdict":"REVISE","confidence":0.6,"blocking_issues":[],"suggestions":[],"per_clause":{}}</json>'
                    }
                }
            ]
        }
    )
    reviewer = OpenAICompatibleReviewer(
        reviewer_id="api",
        model="gpt-test",
        base_url="https://example.test/v1",
        api_key="test",
        transport=transport,
    )

    output = await reviewer.review_round1("plan", timeout_s=1)

    assert output.verdict == Verdict.REVISE
    assert transport.requests[0].url.path == "/v1/chat/completions"


@pytest.mark.asyncio
async def test_openai_compatible_retries_once_when_response_is_malformed():
    transport = SequentialTransport(
        [
            {"choices": [{"message": {"content": "not json"}}]},
            {
                "choices": [
                    {
                        "message": {
                            "content": '<json>{"verdict":"REVISE","confidence":0.7,"blocking_issues":[],"suggestions":[],"per_clause":{}}</json>'
                        }
                    }
                ]
            },
        ]
    )
    reviewer = OpenAICompatibleReviewer(
        reviewer_id="api",
        model="gpt-test",
        base_url="https://example.test/v1",
        api_key="test",
        transport=transport,
    )

    output = await reviewer.review_round1("plan", timeout_s=1)

    assert output.verdict == Verdict.REVISE
    assert output.retries == 1
    assert len(transport.requests) == 2
    assert "not json" in output.raw_response


@pytest.mark.asyncio
async def test_adapter_failure_abstains():
    async def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    reviewer = OllamaReviewer(
        reviewer_id="local",
        model="qwen2.5:14b",
        base_url="http://localhost:11434",
        transport=httpx.MockTransport(boom),
    )

    output = await reviewer.review_round1("plan", timeout_s=1)

    assert output.verdict == Verdict.ABSTAIN
