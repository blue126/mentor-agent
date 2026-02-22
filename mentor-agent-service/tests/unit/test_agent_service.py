"""Unit tests for agent_service — tool use loop logic.

Covers: (a) no tool_use direct text, (b) single tool_use round, (c) multi-round tool_use,
(d) max iteration protection, (e) unknown tool error, (f) tool execution Fail Soft,
(g) malformed JSON arguments Fail Soft.
"""

from unittest.mock import AsyncMock, MagicMock, patch

# --- Mock response helpers ---

def _make_text_response(content="Hello", finish_reason="stop"):
    """Mock a non-tool LLM response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = None
    response.choices[0].finish_reason = finish_reason
    return response


def _make_tool_call_response(tool_name="echo", tool_args='{"message": "hello"}', tool_id="toolu_test123"):
    """Mock a tool_calls LLM response."""
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


# --- Tests ---

class TestRunAgentLoop:
    """Tests for run_agent_loop (non-streaming)."""

    @patch("app.services.agent_service.llm_service")
    async def test_no_tool_use_returns_text_directly(self, mock_llm):
        """(a) LLM returns text without tool_calls → return response directly."""
        from app.services.agent_service import run_agent_loop

        text_resp = _make_text_response("Hello from LLM")
        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value=text_resp)

        messages = [{"role": "user", "content": "Hi"}]
        result = await run_agent_loop(messages)

        assert result is text_resp
        mock_llm.get_chat_completion_with_tools.assert_called_once()

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.llm_service")
    async def test_single_tool_use_round(self, mock_llm, mock_registry):
        """(b) LLM calls echo tool once → tool result → LLM returns text."""
        from app.services.agent_service import run_agent_loop

        tool_resp = _make_tool_call_response("echo", '{"message": "hello"}', "toolu_1")
        text_resp = _make_text_response("Echo result: hello")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=[tool_resp, text_resp])

        mock_echo = AsyncMock(return_value="hello")
        mock_registry.get_tool.return_value = mock_echo
        mock_registry.get_all_schemas.return_value = [{"type": "function", "function": {"name": "echo"}}]
        mock_registry.list_tools.return_value = ["echo"]

        messages = [{"role": "user", "content": "Echo hello"}]
        result = await run_agent_loop(messages)

        assert result is text_resp
        assert mock_llm.get_chat_completion_with_tools.call_count == 2
        mock_echo.assert_called_once_with(message="hello")

        # Verify messages were appended correctly
        assert any(m.get("role") == "tool" and m.get("content") == "hello" for m in messages)

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.llm_service")
    async def test_multi_round_tool_use(self, mock_llm, mock_registry):
        """(c) LLM calls tools twice before returning text."""
        from app.services.agent_service import run_agent_loop

        tool_resp1 = _make_tool_call_response("echo", '{"message": "first"}', "toolu_1")
        tool_resp2 = _make_tool_call_response("echo", '{"message": "second"}', "toolu_2")
        text_resp = _make_text_response("Done")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=[tool_resp1, tool_resp2, text_resp])

        mock_echo = AsyncMock(side_effect=["first", "second"])
        mock_registry.get_tool.return_value = mock_echo
        mock_registry.get_all_schemas.return_value = []
        mock_registry.list_tools.return_value = ["echo"]

        messages = [{"role": "user", "content": "Do two echoes"}]
        result = await run_agent_loop(messages)

        assert result is text_resp
        assert mock_llm.get_chat_completion_with_tools.call_count == 3
        assert mock_echo.call_count == 2

    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.llm_service")
    async def test_max_iteration_protection(self, mock_llm, mock_registry, mock_settings):
        """(d) Loop hits max iterations → returns friendly error string."""
        from app.services.agent_service import run_agent_loop

        mock_settings.max_tool_iterations = 3

        # Always return tool_calls — never stops
        tool_resp = _make_tool_call_response("echo", '{"message": "loop"}', "toolu_loop")
        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value=tool_resp)

        mock_echo = AsyncMock(return_value="looped")
        mock_registry.get_tool.return_value = mock_echo
        mock_registry.get_all_schemas.return_value = []
        mock_registry.list_tools.return_value = ["echo"]

        messages = [{"role": "user", "content": "Loop forever"}]
        result = await run_agent_loop(messages)

        assert isinstance(result, str)
        assert "maximum iterations" in result
        assert "3" in result

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.llm_service")
    async def test_unknown_tool_returns_error_to_llm(self, mock_llm, mock_registry):
        """(e) tool_call references unknown tool → error string fed back to LLM."""
        from app.services.agent_service import run_agent_loop

        tool_resp = _make_tool_call_response("nonexistent_tool", '{}', "toolu_x")
        text_resp = _make_text_response("I see the error")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=[tool_resp, text_resp])
        mock_registry.get_tool.return_value = None
        mock_registry.get_all_schemas.return_value = []
        mock_registry.list_tools.return_value = ["echo"]

        messages = [{"role": "user", "content": "Use unknown tool"}]
        result = await run_agent_loop(messages)

        assert result is text_resp
        # Verify error message was sent back
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert "Unknown tool" in tool_messages[0]["content"]
        assert "echo" in tool_messages[0]["content"]

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.llm_service")
    async def test_tool_execution_fail_soft(self, mock_llm, mock_registry):
        """(f) Tool function raises exception → error string returned to LLM."""
        from app.services.agent_service import run_agent_loop

        tool_resp = _make_tool_call_response("echo", '{"message": "crash"}', "toolu_crash")
        text_resp = _make_text_response("Handled error")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=[tool_resp, text_resp])

        mock_echo = AsyncMock(side_effect=RuntimeError("tool exploded"))
        mock_registry.get_tool.return_value = mock_echo
        mock_registry.get_all_schemas.return_value = []
        mock_registry.list_tools.return_value = ["echo"]

        messages = [{"role": "user", "content": "Crash the tool"}]
        result = await run_agent_loop(messages)

        assert result is text_resp
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        assert "Error: echo failed" in tool_messages[0]["content"]

    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.llm_service")
    async def test_malformed_json_arguments_fail_soft(self, mock_llm, mock_registry):
        """(g) tool_call.function.arguments is invalid JSON → Fail Soft error returned to LLM."""
        from app.services.agent_service import run_agent_loop

        tool_resp = _make_tool_call_response("echo", "not-valid-json{{{", "toolu_bad")
        text_resp = _make_text_response("JSON parse error noted")

        mock_llm.get_chat_completion_with_tools = AsyncMock(side_effect=[tool_resp, text_resp])
        mock_registry.get_all_schemas.return_value = []
        mock_registry.list_tools.return_value = ["echo"]

        messages = [{"role": "user", "content": "Send bad JSON"}]
        result = await run_agent_loop(messages)

        assert result is text_resp
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        assert "Failed to parse arguments" in tool_messages[0]["content"]

    @patch("app.services.agent_service.llm_service")
    async def test_llm_error_returns_error_string(self, mock_llm):
        """LLM returns error string → propagated directly."""
        from app.services.agent_service import run_agent_loop

        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value="Error: LLM service unavailable")
        mock_llm.get_all_schemas = MagicMock(return_value=[])

        messages = [{"role": "user", "content": "Hi"}]
        result = await run_agent_loop(messages)

        assert isinstance(result, str)
        assert "Error" in result


class TestRunAgentLoopStreaming:
    """Tests for run_agent_loop_streaming (SSE async generator)."""

    @patch("app.services.agent_service.litellm")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_no_tool_use_streams_directly(self, mock_llm, mock_settings, mock_litellm):
        """No tool_calls → yields content deltas as SSE events."""
        from app.services.agent_service import run_agent_loop_streaming
        from tests.test_doubles import MockChunk

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        async def _mock_stream():
            yield MockChunk("Hello", finish_reason="stop")

        mock_llm.stream_chat_completion = AsyncMock(return_value=_mock_stream())
        mock_litellm.stream_chunk_builder = MagicMock(
            return_value=_make_text_response("Hello")
        )

        messages = [{"role": "user", "content": "Hi"}]
        events = []
        async for event in run_agent_loop_streaming(messages):
            events.append(event)

        assert any("data: [DONE]" in e for e in events)
        mock_llm.stream_chat_completion.assert_called_once()

    @patch("app.services.agent_service.litellm")
    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_tool_use_then_stream(self, mock_llm, mock_settings, mock_registry, mock_litellm):
        """Tool call → tool result → final text streamed as SSE events."""
        from app.services.agent_service import run_agent_loop_streaming
        from tests.test_doubles import MockChunk

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        tool_resp = _make_tool_call_response("echo", '{"message": "hi"}', "toolu_s1")
        text_resp = _make_text_response("Done streaming")

        async def _tool_stream():
            yield MockChunk(None)

        async def _text_stream():
            yield MockChunk("Done", finish_reason="stop")

        mock_llm.stream_chat_completion = AsyncMock(
            side_effect=[_tool_stream(), _text_stream()]
        )
        mock_litellm.stream_chunk_builder = MagicMock(
            side_effect=[tool_resp, text_resp]
        )

        mock_echo = AsyncMock(return_value="hi")
        mock_registry.get_tool.return_value = mock_echo
        mock_registry.get_all_schemas.return_value = []
        mock_registry.list_tools.return_value = ["echo"]

        messages = [{"role": "user", "content": "Echo hi streaming"}]
        events = []
        async for event in run_agent_loop_streaming(messages):
            events.append(event)

        assert any("data: [DONE]" in e for e in events)
        assert mock_llm.stream_chat_completion.call_count == 2

    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_llm_error_returns_error_in_stream(self, mock_llm, mock_settings):
        """LLM error in streaming path → error status + [DONE] in SSE stream."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        mock_llm.stream_chat_completion = AsyncMock(
            return_value="Error: connection refused"
        )

        messages = [{"role": "user", "content": "Hi"}]
        events = []
        async for event in run_agent_loop_streaming(messages):
            events.append(event)

        assert any("connection refused" in e for e in events)
        assert any("data: [DONE]" in e for e in events)

    @patch("app.services.agent_service.litellm")
    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_buffer_discard_content_on_tool_calls(
        self, mock_llm, mock_settings, mock_registry, mock_litellm
    ):
        """LLM streams content AND requests tool_calls → content is discarded,
        tools execute, only final answer (finish_reason=stop) reaches client."""
        from app.services.agent_service import run_agent_loop_streaming
        from tests.test_doubles import MockChunk

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        mock_registry.get_all_schemas.return_value = [
            {"type": "function", "function": {"name": "echo"}}
        ]
        mock_registry.get_tool.return_value = AsyncMock(return_value="tool-result")

        # Iteration 0: content + tool_calls → content should be DISCARDED
        async def _stream_with_content():
            yield MockChunk("Let me search.")
            yield MockChunk(None, finish_reason="tool_calls")

        # Iteration 1: final answer (stop) → content should be FLUSHED
        async def _stream_final():
            yield MockChunk("Final answer with RAG.", finish_reason="stop")

        mock_llm.stream_chat_completion = AsyncMock(
            side_effect=[_stream_with_content(), _stream_final()]
        )

        tool_resp = _make_tool_call_response("echo", '{"message":"hi"}', "toolu_1")
        tool_resp.choices[0].message.content = "Let me search."
        text_resp = _make_text_response("Final answer with RAG.")

        mock_litellm.stream_chunk_builder = MagicMock(
            side_effect=[tool_resp, text_resp]
        )

        events = []
        async for event in run_agent_loop_streaming(
            messages=[{"role": "user", "content": "test"}],
        ):
            events.append(event)

        event_text = "".join(events)

        # Discarded content NOT in output
        assert "Let me search." not in event_text

        # Tool WAS executed
        assert "Running echo" in event_text
        assert "Thinking" in event_text

        # Only final answer reaches client
        assert "Final answer with RAG." in event_text

        # Two LLM calls (tool iteration + final)
        assert mock_llm.stream_chat_completion.call_count == 2
        assert "data: [DONE]" in event_text

    @patch("app.services.agent_service.litellm")
    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_buffer_multi_step_tools_all_execute(
        self, mock_llm, mock_settings, mock_registry, mock_litellm
    ):
        """Multi-step tool chain: iter 0 content+tools → iter 1 tools only →
        iter 2 final answer.  All tools execute; only final answer shown."""
        from app.services.agent_service import run_agent_loop_streaming
        from tests.test_doubles import MockChunk

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        mock_registry.get_all_schemas.return_value = [
            {"type": "function", "function": {"name": "echo"}}
        ]
        mock_registry.get_tool.return_value = AsyncMock(return_value="tool-result")

        # Iter 0: content + tool_calls (content discarded)
        async def _stream_iter0():
            yield MockChunk("Searching...")
            yield MockChunk(None, finish_reason="tool_calls")

        # Iter 1: tool_calls only (multi-step)
        async def _stream_iter1():
            yield MockChunk(None)

        # Iter 2: final answer
        async def _stream_iter2():
            yield MockChunk("Here is the answer.", finish_reason="stop")

        mock_llm.stream_chat_completion = AsyncMock(
            side_effect=[_stream_iter0(), _stream_iter1(), _stream_iter2()]
        )

        tool_resp_0 = _make_tool_call_response("echo", '{"message":"a"}', "t1")
        tool_resp_0.choices[0].message.content = "Searching..."
        tool_resp_1 = _make_tool_call_response("echo", '{"message":"b"}', "t2")
        text_resp = _make_text_response("Here is the answer.")

        mock_litellm.stream_chunk_builder = MagicMock(
            side_effect=[tool_resp_0, tool_resp_1, text_resp]
        )

        events = []
        async for event in run_agent_loop_streaming(
            messages=[{"role": "user", "content": "test"}],
        ):
            events.append(event)

        event_text = "".join(events)

        # Discarded content NOT in output
        assert "Searching..." not in event_text

        # Both tool iterations executed
        assert event_text.count("Running echo") == 2

        # Only final answer shown
        assert "Here is the answer." in event_text

        # Three LLM calls
        assert mock_llm.stream_chat_completion.call_count == 3
        assert "data: [DONE]" in event_text

    @patch("app.services.agent_service.litellm")
    @patch("app.services.agent_service.registry")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_buffer_normal_flow_flushes_on_stop(
        self, mock_llm, mock_settings, mock_registry, mock_litellm
    ):
        """Normal flow: tool_calls (no content) → final answer (stop).
        Content is buffered then flushed on stop."""
        from app.services.agent_service import run_agent_loop_streaming
        from tests.test_doubles import MockChunk

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        mock_registry.get_all_schemas.return_value = [
            {"type": "function", "function": {"name": "echo"}}
        ]
        mock_registry.get_tool.return_value = AsyncMock(return_value="hello")

        tool_resp = _make_tool_call_response("echo", '{"message":"hello"}', "toolu_n1")
        text_resp = _make_text_response("Final answer.")

        async def _tool_stream():
            yield MockChunk(None)

        async def _text_stream():
            yield MockChunk("Final answer.", finish_reason="stop")

        mock_llm.stream_chat_completion = AsyncMock(
            side_effect=[_tool_stream(), _text_stream()]
        )
        mock_litellm.stream_chunk_builder = MagicMock(
            side_effect=[tool_resp, text_resp]
        )

        events = []
        async for event in run_agent_loop_streaming(
            messages=[{"role": "user", "content": "test"}],
        ):
            events.append(event)

        event_text = "".join(events)

        # Tool was executed normally
        assert "Thinking" in event_text
        assert "Running echo" in event_text

        # Final content flushed
        assert "Final answer." in event_text

        # Two LLM calls
        assert mock_llm.stream_chat_completion.call_count == 2
        assert "data: [DONE]" in event_text
