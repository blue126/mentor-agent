"""SSE (Server-Sent Events) generator for OpenAI-compatible streaming responses."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from app.schemas.chat import ChatCompletionChunk, ChunkChoice, DeltaContent


def make_status_event(text: str, model: str) -> str:
    """Generate SSE event for intermediate status (italic markdown)."""
    chunk = ChatCompletionChunk(
        model=model,
        choices=[ChunkChoice(delta=DeltaContent(content=f"*{text}*\n\n"))],
    )
    return f"data: {json.dumps(chunk.model_dump(exclude_none=True))}\n\n"


def make_done_event() -> str:
    """Generate SSE stream terminator."""
    return "data: [DONE]\n\n"


def make_heartbeat_event() -> str:
    """Generate SSE comment for keepalive (ignored by clients, resets proxy timeouts)."""
    return ": keepalive\n\n"


async def queue_sse_stream(queue: asyncio.Queue[str | None]) -> AsyncIterator[str]:
    """Yield SSE events from queue until None sentinel."""
    while True:
        item = await queue.get()
        if item is None:
            break
        yield item


async def run_heartbeat(
    queue: asyncio.Queue[str | None],
    done: asyncio.Event,
    interval: int = 15,
) -> None:
    """Push heartbeat comments to queue until done is set."""
    while not done.is_set():
        try:
            await asyncio.wait_for(done.wait(), timeout=interval)
            break  # done was set
        except asyncio.TimeoutError:
            await queue.put(make_heartbeat_event())


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
