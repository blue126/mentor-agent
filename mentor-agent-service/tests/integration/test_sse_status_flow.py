"""Integration tests for SSE status flow — Story 1.4.

Verifies: status events appear during tool execution, content deltas follow,
[DONE] terminates the stream, heartbeat present during slow execution,
and backward compatibility with no-tool-call scenarios.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.config import ProviderConfig
from app.main import create_app
from tests.test_doubles import MockChunk

_VALID_TOKEN = "test-secret-key"

_TEST_PROVIDER = ProviderConfig(
    id="test-model",
    display_name="Test Model",
    base_url="http://litellm",
    api_key="test-key",
    model="openai/test-model",
)


def _patch_resolve_provider():
    """Patch resolve_provider so 'test-model' maps to _TEST_PROVIDER."""
    def _mock_resolve(model_id):
        if not model_id or model_id == "test-model":
            return _TEST_PROVIDER
        return None
    return patch("app.routers.chat.resolve_provider", side_effect=_mock_resolve)


async def _mock_stream(*chunks: MockChunk) -> AsyncIterator[MockChunk]:
    for chunk in chunks:
        yield chunk


def _build_client():
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


def _make_tool_call_response(tool_name="echo", tool_args='{"message": "hello"}', tool_id="toolu_status1"):
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


async def test_sse_stream_includes_status_events():
    """Tool use → SSE stream contains status events before content deltas."""
    ac, _ = _build_client()

    tool_resp = _make_tool_call_response("echo", '{"message": "status test"}', "toolu_s1")
    text_resp = _make_text_response("Final answer")

    call_count = 0

    async def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_stream(MockChunk(None))  # tool_call round
        return _mock_stream(MockChunk("Final"), MockChunk(" answer", "stop"))

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.services.agent_service.litellm") as mock_agent_litellm,
        _patch_resolve_provider(),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=_side_effect)
        mock_agent_litellm.stream_chunk_builder = MagicMock(
            side_effect=[tool_resp, text_resp]
        )

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Echo status test"}],
                    "model": "test-model",
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    # Parse SSE events (skip comments and empty lines)
    lines = [line for line in resp.text.split("\n\n") if line.strip() and line.startswith("data:")]

    # Should end with [DONE]
    assert lines[-1].strip() == "data: [DONE]"

    # Parse all JSON data events
    data_events = []
    for line in lines[:-1]:
        payload = line.replace("data: ", "", 1)
        parsed = json.loads(payload)
        assert "choices" in parsed
        data_events.append(parsed)

    # Extract content from delta events
    contents = [
        e["choices"][0]["delta"].get("content", "")
        for e in data_events
        if "delta" in e["choices"][0]
    ]
    all_content = "".join(contents)

    # Should contain status text (italic markdown) for thinking and tool execution
    assert "Thinking" in all_content
    assert "Running echo" in all_content

    # Should contain final answer content
    assert "Final" in all_content
    assert "answer" in all_content


async def test_sse_no_tool_call_no_status_events():
    """No tool_calls → SSE stream has content deltas only, no status events."""
    ac, _ = _build_client()

    text_resp = _make_text_response("Just text")

    async def _side_effect(**kwargs):
        return _mock_stream(MockChunk("Just"), MockChunk(" text", "stop"))

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.services.agent_service.litellm") as mock_agent_litellm,
        _patch_resolve_provider(),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=_side_effect)
        mock_agent_litellm.stream_chunk_builder = MagicMock(
            return_value=text_resp
        )

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
    lines = [line for line in resp.text.split("\n\n") if line.strip() and line.startswith("data:")]
    assert lines[-1].strip() == "data: [DONE]"

    # No status events (no tool icons)
    for line in lines[:-1]:
        payload = line.replace("data: ", "", 1)
        parsed = json.loads(payload)
        content = parsed["choices"][0].get("delta", {}).get("content", "")
        # Should not contain tool status markers (encoded or not)
        assert "Running" not in content
        assert "Thinking" not in content


async def test_non_streaming_no_sse_status():
    """Non-streaming request: standard JSON response, no SSE status events."""
    ac, _ = _build_client()

    tool_resp = _make_tool_call_response("echo", '{"message": "non-stream"}', "toolu_ns")
    text_resp = _make_text_response("Done non-stream")

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
        _patch_resolve_provider(),
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
    assert data["choices"][0]["message"]["content"] == "Done non-stream"
    # No SSE events in non-streaming response
    assert "text/event-stream" not in resp.headers.get("content-type", "")


async def test_multi_tool_call_status_per_round():
    """Multiple tool call rounds → status event per round in SSE stream."""
    ac, _ = _build_client()

    tool_resp1 = _make_tool_call_response("echo", '{"message": "first"}', "toolu_m1")
    tool_resp2 = _make_tool_call_response("echo", '{"message": "second"}', "toolu_m2")
    text_resp = _make_text_response("Both done")

    call_count = 0

    async def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return _mock_stream(MockChunk(None))  # tool_call rounds
        return _mock_stream(MockChunk("Both done", "stop"))

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.services.agent_service.litellm") as mock_agent_litellm,
        _patch_resolve_provider(),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=_side_effect)
        mock_agent_litellm.stream_chunk_builder = MagicMock(
            side_effect=[tool_resp1, tool_resp2, text_resp]
        )

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Two echoes"}],
                    "model": "test-model",
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    lines = [line for line in resp.text.split("\n\n") if line.strip() and line.startswith("data:")]

    # Count status events with tool name
    all_content = ""
    for line in lines[:-1]:
        payload = line.replace("data: ", "", 1)
        parsed = json.loads(payload)
        content = parsed["choices"][0].get("delta", {}).get("content", "")
        all_content += content

    # Two rounds of tool use → two "Running echo" status events
    assert all_content.count("Running echo") == 2
    assert all_content.count("Thinking") == 2
    assert "data: [DONE]" in resp.text


async def test_sse_stream_includes_heartbeat_when_execution_is_slow():
    """Slow tool loop should emit SSE keepalive comments before completion."""
    ac, _ = _build_client()

    tool_resp = _make_tool_call_response("echo", '{"message": "slow"}', "toolu_hb1")
    text_resp = _make_text_response("Slow done")

    call_count = 0

    async def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Slow first streaming call — heartbeat should fire during this
            await asyncio.sleep(0.1)
            return _mock_stream(MockChunk(None))  # tool_call round
        return _mock_stream(MockChunk("Slow"), MockChunk(" done", "stop"))

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.agent_service.settings") as mock_agent_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.services.agent_service.litellm") as mock_agent_litellm,
        _patch_resolve_provider(),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_agent_settings.max_tool_iterations = 10
        mock_agent_settings.sse_heartbeat_interval = 0.02
        mock_litellm.acompletion = AsyncMock(side_effect=_side_effect)
        mock_agent_litellm.stream_chunk_builder = MagicMock(
            side_effect=[tool_resp, text_resp]
        )

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Run echo tool slowly"}],
                    "model": "test-model",
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "chatcmpl-heartbeat" in resp.text
    assert "data: [DONE]" in resp.text
