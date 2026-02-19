"""SSE (Server-Sent Events) generator for OpenAI-compatible streaming responses."""

import json
from collections.abc import AsyncIterator
from typing import Any


async def sse_stream(response_stream: AsyncIterator[Any]) -> AsyncIterator[str]:
    """Convert a LiteLLM streaming response into OpenAI SSE format lines.

    Yields 'data: {json}\\n\\n' lines followed by 'data: [DONE]\\n\\n'.
    Handles mid-stream errors gracefully.
    """
    try:
        async for chunk in response_stream:
            chunk_dict = chunk.model_dump(exclude_none=True)
            yield f"data: {json.dumps(chunk_dict)}\n\n"
    except Exception as exc:
        error_payload = {
            "id": "chatcmpl-error",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "error",
            "choices": [{"index": 0, "delta": {"content": f"[Error: {exc}]"}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(error_payload)}\n\n"
    yield "data: [DONE]\n\n"
