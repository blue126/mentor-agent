"""Integration tests for tool use flow — end-to-end through the HTTP endpoint.

Mock LLM returns tool_use → agent executes echo → LLM returns final text → SSE output.
"""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.test_doubles import MockChunk

_VALID_TOKEN = "test-secret-key"


async def _mock_stream(*chunks: MockChunk) -> AsyncIterator[MockChunk]:
    for chunk in chunks:
        yield chunk


def _build_client():
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


def _make_tool_call_response(tool_name="echo", tool_args='{"message": "hello"}', tool_id="toolu_int1"):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].finish_reason = "tool_calls"

    tool_call = MagicMock()
    tool_call.id = tool_id
    tool_call.function.name = tool_name
    tool_call.function.arguments = tool_args

    response.choices[0].message = MagicMock()
    response.choices[0].message.content = None
    response.choices[0].message.tool_calls = [tool_call]
    response.choices[0].message.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": tool_id,
            "type": "function",
            "function": {"name": tool_name, "arguments": tool_args},
        }],
    }
    return response


def _make_text_response(content="Done"):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = None
    response.choices[0].finish_reason = "stop"
    response.choices[0].message.role = "assistant"
    response.usage = MagicMock()
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    response.usage.total_tokens = 15
    response.model = "test-model"
    return response


async def test_streaming_tool_use_flow():
    """Full flow: POST → agent detects tool_use → executes echo → streams final text as SSE."""
    ac, _ = _build_client()

    tool_resp = _make_tool_call_response("echo", '{"message": "integration test"}', "toolu_flow1")
    text_resp = _make_text_response("Echo complete")
    mock_stream = _mock_stream(MockChunk("Echo"), MockChunk(" complete", "stop"))

    # Track calls to handle two-phase: non-streaming tool check, then non-streaming final, then streaming
    call_count = 0

    async def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if kwargs.get("stream"):
            return mock_stream
        if call_count == 1:
            return tool_resp
        return text_resp

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=_side_effect)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Echo integration test"}],
                    "model": "test-model",
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    lines = [line for line in resp.text.split("\n\n") if line.strip() and line.startswith("data:")]
    assert lines[-1].strip() == "data: [DONE]"

    # Verify at least one data chunk has content
    data_chunks = []
    for line in lines[:-1]:
        payload = line.replace("data: ", "", 1)
        parsed = json.loads(payload)
        assert "choices" in parsed
        data_chunks.append(parsed)
    assert len(data_chunks) >= 1


async def test_non_streaming_tool_use_flow():
    """Non-streaming: tool_use → echo → final JSON response."""
    ac, _ = _build_client()

    tool_resp = _make_tool_call_response("echo", '{"message": "non-stream test"}', "toolu_ns1")
    text_resp = _make_text_response("Echo done")

    mock_llm_calls = [tool_resp, text_resp]
    call_idx = 0

    async def _side_effect(**kwargs):
        nonlocal call_idx
        resp = mock_llm_calls[call_idx]
        call_idx += 1
        return resp

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=_side_effect)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Echo non-stream"}],
                    "model": "test-model",
                    "stream": False,
                },
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "Echo done"
    assert data["choices"][0]["finish_reason"] == "stop"


async def test_no_tool_use_backwards_compatible_streaming():
    """Without tool_calls, streaming behavior is identical to Story 1.2."""
    ac, _ = _build_client()

    text_resp = _make_text_response("Just text")
    mock_stream = _mock_stream(MockChunk("Just"), MockChunk(" text", "stop"))

    async def _side_effect(**kwargs):
        if kwargs.get("stream"):
            return mock_stream
        return text_resp

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=_side_effect)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "model": "test-model",
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    lines = [line for line in resp.text.split("\n\n") if line.strip() and line.startswith("data:")]
    assert lines[-1].strip() == "data: [DONE]"


async def test_no_tool_use_backwards_compatible_non_streaming():
    """Without tool_calls, non-streaming behavior is identical to Story 1.2."""
    ac, _ = _build_client()

    text_resp = _make_text_response("Just JSON")

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(return_value=text_resp)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "model": "test-model",
                    "stream": False,
                },
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "Just JSON"
