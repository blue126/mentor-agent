"""LLM proxy service — thin wrapper around LiteLLM for streaming and non-streaming calls."""

from collections.abc import AsyncIterator
from typing import Any, cast

import litellm

from app.config import settings


# URL markers indicating direct Anthropic API access (no openai/ prefix needed).
# When base_url points to a proxy (claude-max-proxy, LiteLLM), models need
# the "openai/" prefix so LiteLLM treats them as OpenAI-compatible targets.
# P2: once LITELLM_* naming is neutralised, this sniffing can be simplified.
_DIRECT_API_URL_MARKERS = ("api.anthropic.com",)


def _normalize_model_for_litellm(model: str) -> str:
    """Add 'openai/' prefix when routing through a proxy, skip for direct API."""
    if "/" in model:
        return model

    base_url = settings.litellm_base_url.lower()
    if any(marker in base_url for marker in _DIRECT_API_URL_MARKERS):
        return model

    return f"openai/{model}"


def _completion_kwargs(
    messages: list[dict[str, str]],
    stream: bool,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    selected_model = _normalize_model_for_litellm(model or settings.litellm_model)
    kwargs: dict[str, Any] = {
        "model": selected_model,
        "messages": messages,
        "api_base": settings.litellm_base_url,
        "api_key": settings.litellm_key,
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
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
) -> Any | str:
    try:
        return await litellm.acompletion(
            **_completion_kwargs(
                messages=messages,
                stream=stream,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
    except Exception as exc:
        return f"Error: LLM service unavailable — {exc}"


async def stream_chat_completion(
    messages: list[dict[str, str]],
    model: str | None = None,
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
            model=model,
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
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any | str:
    """Get a non-streaming chat completion. Returns response object or error string on failure."""
    return await _run_completion(
        messages=messages,
        stream=False,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def get_chat_completion_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str = "auto",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any | str:
    """Non-streaming completion with tool definitions. Returns response object or error string."""
    try:
        kwargs = _completion_kwargs(
            messages=messages,
            stream=False,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        return await litellm.acompletion(**kwargs)
    except Exception as exc:
        return f"Error: LLM service unavailable — {exc}"
