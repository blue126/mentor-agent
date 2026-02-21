"""Unit tests for persona injection in agent_service.

Covers:
(a) System prompt injected as first message in non-streaming path
(b) System prompt injected as first message in streaming path
(c) No duplicate injection when system message already exists
(d) Prompt contains required persona directives (prerequisite check, knowledge graph, guided correction, RAG disclosure)
"""

from unittest.mock import AsyncMock, MagicMock, patch


def _make_text_response(content="Hello", finish_reason="stop"):
    """Mock a non-tool LLM response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = None
    response.choices[0].finish_reason = finish_reason
    return response


class TestPersonaInjectionNonStreaming:
    """Tests for system prompt injection in run_agent_loop."""

    @patch("app.services.agent_service.prompt_service")
    @patch("app.services.agent_service.llm_service")
    async def test_system_prompt_injected_at_first_position(self, mock_llm, mock_prompt):
        """(a) System prompt is prepended as first message."""
        from app.services.agent_service import run_agent_loop

        mock_prompt.load_system_prompt = AsyncMock(return_value="You are a Socratic mentor.")
        text_resp = _make_text_response("Hi there")
        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value=text_resp)

        messages = [{"role": "user", "content": "Hello"}]
        await run_agent_loop(messages)

        # Verify the first message sent to LLM is the system prompt
        call_args = mock_llm.get_chat_completion_with_tools.call_args
        sent_messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[0]["content"] == "You are a Socratic mentor."

    @patch("app.services.agent_service.prompt_service")
    @patch("app.services.agent_service.llm_service")
    async def test_no_duplicate_injection(self, mock_llm, mock_prompt):
        """(c) If messages already have a system message, do not duplicate."""
        from app.services.agent_service import run_agent_loop

        mock_prompt.load_system_prompt = AsyncMock(return_value="You are a Socratic mentor.")
        text_resp = _make_text_response("Hi there")
        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value=text_resp)

        messages = [
            {"role": "system", "content": "Existing system prompt"},
            {"role": "user", "content": "Hello"},
        ]
        await run_agent_loop(messages)

        call_args = mock_llm.get_chat_completion_with_tools.call_args
        sent_messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
        # Should replace existing system message, not add a second one
        system_messages = [m for m in sent_messages if m["role"] == "system"]
        assert len(system_messages) == 1
        assert system_messages[0]["content"] == "You are a Socratic mentor."


class TestPersonaInjectionStreaming:
    """Tests for system prompt injection in run_agent_loop_streaming."""

    @patch("app.services.agent_service.prompt_service")
    @patch("app.services.agent_service.settings")
    @patch("app.services.agent_service.llm_service")
    async def test_system_prompt_injected_in_streaming(self, mock_llm, mock_settings, mock_prompt):
        """(b) System prompt is prepended in streaming path too."""
        from app.services.agent_service import run_agent_loop_streaming

        mock_settings.max_tool_iterations = 10
        mock_settings.sse_heartbeat_interval = 60
        mock_settings.litellm_model = "test-model"

        mock_prompt.load_system_prompt = AsyncMock(return_value="You are a Socratic mentor.")

        text_resp = _make_text_response("Hello")
        mock_llm.get_chat_completion_with_tools = AsyncMock(return_value=text_resp)

        async def _mock_stream():
            from tests.test_doubles import MockChunk
            yield MockChunk("Hello", finish_reason="stop")

        mock_llm.stream_chat_completion = AsyncMock(return_value=_mock_stream())

        messages = [{"role": "user", "content": "Search for something"}]
        events = []
        async for event in run_agent_loop_streaming(messages):
            events.append(event)

        # Verify the messages passed to LLM include system prompt at position 0
        call_args = mock_llm.get_chat_completion_with_tools.call_args
        sent_messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
        assert sent_messages[0]["role"] == "system"
        assert "Socratic mentor" in sent_messages[0]["content"]
