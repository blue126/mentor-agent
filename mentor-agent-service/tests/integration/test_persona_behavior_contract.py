"""Integration tests for persona behavior contract.

Verifies that the LLM receives messages with system prompt containing
key persona directives, for both stream=false and stream=true paths.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.test_doubles import MockChunk

_VALID_TOKEN = "test-secret-key"
_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_SYSTEM_PROMPT_PATH = str(_SERVICE_ROOT / "app" / "prompts" / "mentor_system_prompt.md")
_MESSAGES_PAYLOAD = {"messages": [{"role": "user", "content": "Hello"}], "model": "test-model"}

# Key directives that MUST appear in the system prompt
_REQUIRED_DIRECTIVES = [
    "prerequisite",       # Prerequisite Check
    "knowledge graph",    # Knowledge Graph Linking (case-insensitive check)
    "guiding question",   # Guided Correction
    "knowledge base",     # RAG Limitation Disclosure
]


def _make_text_response(content="Hi there!", finish_reason="stop"):
    return type(
        "Response", (),
        {
            "choices": [
                type("Choice", (), {
                    "message": type("Msg", (), {
                        "role": "assistant", "content": content, "tool_calls": None,
                    })(),
                    "finish_reason": finish_reason,
                })()
            ],
            "usage": type("Usage", (), {
                "prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8,
            })(),
            "model": "test-model",
        },
    )()


async def _mock_stream_response(*chunks: MockChunk) -> AsyncIterator[MockChunk]:
    for chunk in chunks:
        yield chunk


def _make_stream_aware_mock(non_stream_response, stream_response):
    async def _side_effect(**kwargs):
        if kwargs.get("stream"):
            return stream_response
        return non_stream_response
    return _side_effect


def _build_client():
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


def _extract_system_prompt_from_calls(mock_litellm) -> str:
    """Extract the system prompt content from captured litellm.acompletion calls."""
    for call in mock_litellm.acompletion.call_args_list:
        messages = call.kwargs.get("messages", [])
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "system":
                return msg["content"]
    return ""


async def test_non_streaming_includes_persona_directives():
    """Non-streaming: LLM receives system prompt with all required persona directives."""
    ac, app = _build_client()

    mock_response = _make_text_response("I'll guide you through this.")

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.services.prompt_service.settings") as mock_prompt_settings,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_prompt_settings.mentor_mode_enabled = True
        mock_prompt_settings.system_prompt_path = _SYSTEM_PROMPT_PATH
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={**_MESSAGES_PAYLOAD, "stream": False},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200

    system_prompt = _extract_system_prompt_from_calls(mock_litellm)
    assert system_prompt, "System prompt was not injected into LLM request"

    prompt_lower = system_prompt.lower()
    for directive in _REQUIRED_DIRECTIVES:
        assert directive.lower() in prompt_lower, (
            f"Missing required directive '{directive}' in system prompt"
        )


async def test_streaming_includes_persona_directives():
    """Streaming: LLM receives system prompt with all required persona directives."""
    ac, app = _build_client()

    text_resp = _make_text_response("Hello world")

    async def _side_effect(**kwargs):
        return _mock_stream_response(MockChunk("Hello"), MockChunk(" world", "stop"))

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.services.agent_service.litellm") as mock_agent_litellm,
        patch("app.services.prompt_service.settings") as mock_prompt_settings,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_prompt_settings.mentor_mode_enabled = True
        mock_prompt_settings.system_prompt_path = _SYSTEM_PROMPT_PATH
        mock_litellm.acompletion = AsyncMock(side_effect=_side_effect)
        mock_agent_litellm.stream_chunk_builder = MagicMock(
            return_value=text_resp
        )

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={**_MESSAGES_PAYLOAD, "stream": True},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200

    system_prompt = _extract_system_prompt_from_calls(mock_litellm)
    assert system_prompt, "System prompt was not injected into streaming LLM request"

    prompt_lower = system_prompt.lower()
    for directive in _REQUIRED_DIRECTIVES:
        assert directive.lower() in prompt_lower, (
            f"Missing required directive '{directive}' in streaming system prompt"
        )


async def test_system_prompt_is_first_message():
    """System prompt must be the first message in the messages list sent to LLM."""
    ac, app = _build_client()

    mock_response = _make_text_response("Sure!")

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={**_MESSAGES_PAYLOAD, "stream": False},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200

    call_args = mock_litellm.acompletion.call_args
    messages = call_args.kwargs.get("messages", [])
    assert messages[0]["role"] == "system", "First message must be system prompt"
    assert messages[1]["role"] == "user", "User message should follow system prompt"


async def test_mentor_mode_disabled_uses_neutral_prompt():
    """When mentor_mode_enabled=False, system prompt is neutral (no Socratic directives)."""
    ac, app = _build_client()

    mock_response = _make_text_response("Hi!")

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.services.prompt_service.settings") as mock_prompt_settings,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        mock_prompt_settings.mentor_mode_enabled = False

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={**_MESSAGES_PAYLOAD, "stream": False},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200

    system_prompt = _extract_system_prompt_from_calls(mock_litellm)
    assert "assistant" in system_prompt.lower()
    assert "socratic" not in system_prompt.lower()
