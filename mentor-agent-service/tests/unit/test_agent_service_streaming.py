"""Unit tests for run_agent_loop_streaming — SSE status updates.

Covers: (a) no tool_use direct stream, (b) single tool_use with status,
(c) multi-round tool_use with status per round, (d) max iteration protection,
(e) tool execution Fail Soft, (f) queue [DONE] and None sentinel,
(g) early exit task cleanup, (h) malformed JSON Fail Soft.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_doubles import MockChunk

# --- Mock response helpers (reused from test_agent_service.py) ---

def _make_text_response(content="Hello", finish_reason="stop"):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = None
    response.choices[0].finish_reason = finish_reason
    return response


def _make_tool_call_response(tool_name="echo", tool_args='{"message": "hello"}', tool_id="toolu_test123"):
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


async def _make_async_stream(*chunks):
    """Create an async iterator from MockChunk instances."""
    for c in chunks:
        yield c


async def _collect_events(async_iter):
    """Collect all events from an async iterator."""
    events = []
    async for event in async_iter:
        events.append(event)
    return events


# --- Tests ---

class TestRunAgentLoopStreamingSSE:
    """Tests for the new SSE-status-aware run_agent_loop_streaming."""

    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_no_tool_call_streams_directly(self, mock_llm, mock_settings):
        """(a) No tool_calls → streams content deltas, no status events."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        text_resp = _make_text_response("Hello")
        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value=text_resp)

        stream_chunks = [MockChunk("Hello"), MockChunk(" world", finish_reason="stop")]
        mock_llm.stream_chat_completion = AsyncMock(
            return_value=_make_async_stream(*stream_chunks)
        )

        messages = [{"role": "user", "content": "Hi"}]
        events = await _collect_events(run_agent_loop_streaming(messages, "test-model"))

        # Should have content deltas and [DONE], no tool status events
        assert any("data: [DONE]" in e for e in events)
        assert not any("🔧" in e for e in events)
        # Content chunks should be present
        data_events = [e for e in events if e.startswith("data: {")]
        assert len(data_events) >= 1

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_single_tool_call_emits_status(self, mock_llm, mock_settings, mock_registry):
        """(b) Single tool_call → status events + content deltas."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        tool_resp = _make_tool_call_response("echo", '{"message": "hi"}', "toolu_1")
        text_resp = _make_text_response("Echo says hi")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=[tool_resp, text_resp])
        stream_chunks = [MockChunk("Echo says hi", finish_reason="stop")]
        mock_llm.stream_chat_completion = AsyncMock(
            return_value=_make_async_stream(*stream_chunks)
        )

        mock_echo = AsyncMock(return_value="hi")
        mock_registry.get_tool.return_value = mock_echo
        mock_registry.get_all_schemas.return_value = [{"type": "function", "function": {"name": "echo"}}]

        messages = [{"role": "user", "content": "Echo hi"}]
        events = await _collect_events(run_agent_loop_streaming(messages, "test-model"))

        # Should contain thinking status
        thinking_events = [e for e in events if "Thinking" in e]
        assert len(thinking_events) >= 1

        # Should contain tool status
        tool_status_events = [e for e in events if "Running echo" in e]
        assert len(tool_status_events) == 1

        # Should end with [DONE]
        assert any("data: [DONE]" in e for e in events)

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_multi_round_tool_use_status_per_round(self, mock_llm, mock_settings, mock_registry):
        """(c) Multi-round tool calls → status events per round."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        tool_resp1 = _make_tool_call_response("echo", '{"message": "first"}', "toolu_1")
        tool_resp2 = _make_tool_call_response("echo", '{"message": "second"}', "toolu_2")
        text_resp = _make_text_response("Done")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=[tool_resp1, tool_resp2, text_resp])
        stream_chunks = [MockChunk("Done", finish_reason="stop")]
        mock_llm.stream_chat_completion = AsyncMock(
            return_value=_make_async_stream(*stream_chunks)
        )

        mock_echo = AsyncMock(side_effect=["first", "second"])
        mock_registry.get_tool.return_value = mock_echo
        mock_registry.get_all_schemas.return_value = []

        messages = [{"role": "user", "content": "Two echoes"}]
        events = await _collect_events(run_agent_loop_streaming(messages, "test-model"))

        # Two rounds → two thinking + two tool status
        thinking_events = [e for e in events if "Thinking" in e]
        assert len(thinking_events) == 2
        tool_events = [e for e in events if "Running echo" in e]
        assert len(tool_events) == 2
        assert any("data: [DONE]" in e for e in events)

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_max_iteration_protection(self, mock_llm, mock_settings, mock_registry):
        """(d) Max iterations → friendly status message + [DONE]."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 2
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        # Always returns tool_calls
        tool_resp = _make_tool_call_response("echo", '{"message": "loop"}', "toolu_loop")
        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value=tool_resp)

        mock_echo = AsyncMock(return_value="looped")
        mock_registry.get_tool.return_value = mock_echo
        mock_registry.get_all_schemas.return_value = []

        messages = [{"role": "user", "content": "Loop"}]
        events = await _collect_events(run_agent_loop_streaming(messages, "test-model"))

        # Should contain max iterations warning
        max_iter_events = [e for e in events if "maximum" in e.lower() or "iterations" in e.lower()]
        assert len(max_iter_events) >= 1
        assert any("data: [DONE]" in e for e in events)

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_tool_execution_fail_soft(self, mock_llm, mock_settings, mock_registry):
        """(e) Tool raises exception → error status event, stream continues."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        tool_resp = _make_tool_call_response("echo", '{"message": "crash"}', "toolu_crash")
        text_resp = _make_text_response("Handled error")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=[tool_resp, text_resp])
        stream_chunks = [MockChunk("Handled error", finish_reason="stop")]
        mock_llm.stream_chat_completion = AsyncMock(
            return_value=_make_async_stream(*stream_chunks)
        )

        mock_echo = AsyncMock(side_effect=RuntimeError("tool exploded"))
        mock_registry.get_tool.return_value = mock_echo
        mock_registry.get_all_schemas.return_value = []

        messages = [{"role": "user", "content": "Crash"}]
        events = await _collect_events(run_agent_loop_streaming(messages, "test-model"))

        # Tool error is fed back to LLM, stream should still complete
        assert any("data: [DONE]" in e for e in events)
        # Verify tool error was fed back as tool result (not a status event crash)
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert any("failed" in m["content"] for m in tool_msgs)

    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_done_event_and_sentinel(self, mock_llm, mock_settings):
        """(f) Stream always ends with [DONE] event."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        text_resp = _make_text_response("Hi")
        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value=text_resp)
        stream_chunks = [MockChunk("Hi", finish_reason="stop")]
        mock_llm.stream_chat_completion = AsyncMock(
            return_value=_make_async_stream(*stream_chunks)
        )

        messages = [{"role": "user", "content": "Hi"}]
        events = await _collect_events(run_agent_loop_streaming(messages, "test-model"))

        # Last non-empty event should be [DONE]
        assert events[-1] == "data: [DONE]\n\n"

    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_llm_error_emits_status_and_done(self, mock_llm, mock_settings):
        """LLM error → error status event + [DONE]."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        mock_llm.get_chat_completion_with_tools = AsyncMock(
            return_value="Error: LLM service unavailable"
        )

        messages = [{"role": "user", "content": "Hi"}]
        events = await _collect_events(run_agent_loop_streaming(messages, "test-model"))

        # Should contain error status and [DONE]
        # Note: json.dumps escapes non-ASCII, so check for text portion
        error_events = [e for e in events if "LLM service unavailable" in e]
        assert len(error_events) >= 1
        assert any("data: [DONE]" in e for e in events)

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_malformed_json_arguments_fail_soft(self, mock_llm, mock_settings, mock_registry):
        """(h) Malformed JSON in tool args → Fail Soft, stream continues."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        tool_resp = _make_tool_call_response("echo", "not-valid-json{{{", "toolu_bad")
        text_resp = _make_text_response("JSON error noted")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=[tool_resp, text_resp])
        stream_chunks = [MockChunk("JSON error noted", finish_reason="stop")]
        mock_llm.stream_chat_completion = AsyncMock(
            return_value=_make_async_stream(*stream_chunks)
        )

        mock_registry.get_all_schemas.return_value = []

        messages = [{"role": "user", "content": "Bad JSON"}]
        events = await _collect_events(run_agent_loop_streaming(messages, "test-model"))

        # Stream should complete normally
        assert any("data: [DONE]" in e for e in events)
        # Malformed JSON error fed back to LLM as tool result
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert any("Failed to parse arguments" in m["content"] for m in tool_msgs)

    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_stream_error_emits_status_and_done(self, mock_llm, mock_settings):
        """Stream_chat_completion returns error → error status + [DONE]."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        text_resp = _make_text_response("Hi")
        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value=text_resp)
        mock_llm.stream_chat_completion = AsyncMock(
            return_value="Error: stream failed"
        )

        messages = [{"role": "user", "content": "Hi"}]
        events = await _collect_events(run_agent_loop_streaming(messages, "test-model"))

        error_events = [e for e in events if "stream failed" in e]
        assert len(error_events) >= 1
        assert any("data: [DONE]" in e for e in events)

    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_early_close_cancels_and_converges(self, mock_llm, mock_settings):
        """(g) Early stream close should cancel tasks and finish quickly."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 0.05
        mock_settings.litellm_model = "test-model"

        async def _hanging_completion(**kwargs):
            await asyncio.sleep(10)
            return _make_text_response("late")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=_hanging_completion)
        mock_llm.stream_chat_completion = AsyncMock()

        messages = [{"role": "user", "content": "Hi"}]
        gen = run_agent_loop_streaming(messages, "test-model")

        first_event = await asyncio.wait_for(anext(gen), timeout=1.0)
        assert first_event == ": keepalive\n\n"

        await asyncio.wait_for(gen.aclose(), timeout=1.0)

        with pytest.raises(StopAsyncIteration):
            await anext(gen)
