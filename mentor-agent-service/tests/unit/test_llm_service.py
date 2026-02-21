"""Unit tests for LLM proxy service."""

from unittest.mock import AsyncMock, patch

from app.services.llm_service import get_chat_completion, stream_chat_completion
from tests.test_doubles import MockChunk

_MESSAGES = [{"role": "user", "content": "Hello"}]

async def _mock_async_iterator(*chunks):
    for chunk in chunks:
        yield chunk


@patch("app.services.llm_service.litellm")
async def test_stream_chat_completion_returns_async_generator(mock_litellm):
    """stream_chat_completion should return an async generator yielding chunks."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_mock_async_iterator(MockChunk("Hi"), MockChunk(None, "stop"))
    )

    stream = await stream_chat_completion(_MESSAGES, "test-model")
    assert not isinstance(stream, str)

    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert len(chunks) == 2
    mock_litellm.acompletion.assert_called_once()


@patch("app.services.llm_service.litellm")
async def test_get_chat_completion_returns_text_content(mock_litellm):
    """get_chat_completion should extract and return text content string."""
    msg = type("Msg", (), {"role": "assistant", "content": "Hello!"})()
    choice = type("Choice", (), {"message": msg, "finish_reason": "stop"})()
    usage = type("Usage", (), {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8})()
    mock_response = type("Response", (), {
        "choices": [choice],
        "usage": usage,
        "model": "test-model",
    })()
    mock_litellm.acompletion = AsyncMock(return_value=mock_response)

    result = await get_chat_completion(_MESSAGES, "test-model")
    assert isinstance(result, str)
    assert result == "Hello!"


@patch("app.services.llm_service.litellm")
async def test_stream_chat_completion_fail_soft(mock_litellm):
    """Connection errors should return an error string, not crash."""
    mock_litellm.acompletion = AsyncMock(side_effect=Exception("Connection refused"))

    result = await stream_chat_completion(_MESSAGES, "test-model")
    assert isinstance(result, str)
    assert "Error" in result


@patch("app.services.llm_service.litellm")
async def test_get_chat_completion_fail_soft(mock_litellm):
    """Non-streaming path should also fail soft on errors."""
    mock_litellm.acompletion = AsyncMock(side_effect=Exception("Connection refused"))

    result = await get_chat_completion(_MESSAGES, "test-model")
    assert isinstance(result, str)
    assert "Error" in result


@patch("app.services.llm_service.settings")
@patch("app.services.llm_service.litellm")
async def test_stream_chat_completion_uses_config_model_when_request_model_missing(mock_litellm, mock_settings):
    mock_settings.litellm_model = "model-from-config"
    mock_settings.litellm_base_url = "http://litellm"
    mock_settings.litellm_key = "test-key"
    mock_litellm.acompletion = AsyncMock(return_value=_mock_async_iterator(MockChunk("Hi")))

    await stream_chat_completion(_MESSAGES, model=None)

    call_kwargs = mock_litellm.acompletion.call_args.kwargs
    assert call_kwargs["model"] == "openai/model-from-config"
