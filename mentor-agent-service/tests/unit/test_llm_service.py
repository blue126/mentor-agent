"""Unit tests for LLM proxy service."""

from unittest.mock import AsyncMock, patch

from app.config import ProviderConfig
from app.services.llm_service import _completion_kwargs, get_chat_completion, stream_chat_completion
from tests.test_doubles import MockChunk

_MESSAGES = [{"role": "user", "content": "Hello"}]

_TEST_PROVIDER = ProviderConfig(
    id="test-model",
    display_name="Test Model",
    base_url="http://litellm",
    api_key="test-key",
    model="openai/test-model",
)


async def _mock_async_iterator(*chunks):
    for chunk in chunks:
        yield chunk


@patch("app.services.llm_service.litellm")
async def test_stream_chat_completion_returns_async_generator(mock_litellm):
    """stream_chat_completion should return an async generator yielding chunks."""
    mock_litellm.acompletion = AsyncMock(
        return_value=_mock_async_iterator(MockChunk("Hi"), MockChunk(None, "stop"))
    )

    stream = await stream_chat_completion(_MESSAGES, _TEST_PROVIDER)
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

    result = await get_chat_completion(_MESSAGES, _TEST_PROVIDER)
    assert isinstance(result, str)
    assert result == "Hello!"


@patch("app.services.llm_service.litellm")
async def test_stream_chat_completion_fail_soft(mock_litellm):
    """Connection errors should return an error string, not crash."""
    mock_litellm.acompletion = AsyncMock(side_effect=Exception("Connection refused"))

    result = await stream_chat_completion(_MESSAGES, _TEST_PROVIDER)
    assert isinstance(result, str)
    assert "Error" in result


@patch("app.services.llm_service.litellm")
async def test_get_chat_completion_fail_soft(mock_litellm):
    """Non-streaming path should also fail soft on errors."""
    mock_litellm.acompletion = AsyncMock(side_effect=Exception("Connection refused"))

    result = await get_chat_completion(_MESSAGES, _TEST_PROVIDER)
    assert isinstance(result, str)
    assert "Error" in result


def test_completion_kwargs_uses_provider_config():
    """_completion_kwargs should use provider config for model, api_base, api_key."""
    provider = ProviderConfig(
        id="custom-provider",
        display_name="Custom",
        base_url="http://custom-proxy:1234/v1",
        api_key="custom-key-123",
        model="openai/custom-model",
    )
    kwargs = _completion_kwargs(
        messages=_MESSAGES,
        stream=False,
        provider=provider,
        temperature=0.5,
        max_tokens=100,
    )
    assert kwargs["model"] == "openai/custom-model"
    assert kwargs["api_base"] == "http://custom-proxy:1234/v1"
    assert kwargs["api_key"] == "custom-key-123"
    assert kwargs["temperature"] == 0.5
    assert kwargs["max_tokens"] == 100
    assert kwargs["stream"] is False
