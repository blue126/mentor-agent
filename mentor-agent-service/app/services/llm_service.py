"""LLM proxy service — thin wrapper around LiteLLM for streaming and non-streaming calls."""

from collections.abc import AsyncIterator
from typing import Any, cast

import litellm

from app.config import ProviderConfig


def _completion_kwargs(
    messages: list[dict[str, str]],
    stream: bool,
    provider: ProviderConfig,
    temperature: float | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": provider.model,
        "messages": messages,
        "api_base": provider.base_url,
        "api_key": provider.api_key,
        "stream": stream,
        "timeout": 600,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return kwargs


async def _run_completion(
    messages: list[dict[str, str]],
    stream: bool,
    provider: ProviderConfig,
    temperature: float | None,
    max_tokens: int | None,
) -> Any | str:
    try:
        return await litellm.acompletion(
            **_completion_kwargs(
                messages=messages,
                stream=stream,
                provider=provider,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
    except Exception as exc:
        return f"Error: LLM service unavailable — {exc}"


async def stream_chat_completion(
    messages: list[dict[str, str]],
    provider: ProviderConfig,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str = "auto",
) -> AsyncIterator[Any] | str:
    """Stream a chat completion via LiteLLM. Returns async iterator or error string on failure."""
    try:
        kwargs = _completion_kwargs(
            messages=messages,
            stream=True,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        result = await litellm.acompletion(**kwargs)
    except Exception as exc:
        return f"Error: LLM service unavailable — {exc}"
    if isinstance(result, str):
        return result
    return cast(AsyncIterator[Any], result)


async def get_chat_completion(
    messages: list[dict[str, str]],
    provider: ProviderConfig,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Get a non-streaming chat completion. Returns text content or error string on failure."""
    result = await _run_completion(
        messages=messages,
        stream=False,
        provider=provider,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if isinstance(result, str):
        return result
    try:
        return result.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        return "Error: LLM returned unexpected response format"


async def get_chat_completion_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str = "auto",
    *,
    provider: ProviderConfig,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any | str:
    """Non-streaming completion with tool definitions. Returns response object or error string."""
    try:
        kwargs = _completion_kwargs(
            messages=messages,
            stream=False,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        return await litellm.acompletion(**kwargs)
    except Exception as exc:
        return f"Error: LLM service unavailable — {exc}"
