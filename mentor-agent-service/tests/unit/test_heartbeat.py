"""Unit tests for heartbeat coroutine and queue_sse_stream.

Covers: heartbeat sends keepalive at interval, stops on done event,
queue_sse_stream yields items and terminates on None sentinel.
"""

import asyncio


async def test_heartbeat_sends_keepalive():
    """Heartbeat pushes keepalive events at the configured interval."""
    from app.utils.sse_generator import run_heartbeat

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    done = asyncio.Event()
    task = asyncio.create_task(run_heartbeat(queue, done, interval=0.1))
    await asyncio.sleep(0.35)
    done.set()
    await task
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert len(events) >= 2
    assert all(e.startswith("data: ") and "chatcmpl-heartbeat" in e for e in events)


async def test_heartbeat_stops_on_done():
    """Heartbeat exits immediately when done is already set."""
    from app.utils.sse_generator import run_heartbeat

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    done = asyncio.Event()
    done.set()  # Already done
    task = asyncio.create_task(run_heartbeat(queue, done, interval=1))
    await task  # Should return immediately
    assert queue.empty()


async def test_heartbeat_does_not_leak():
    """Heartbeat task completes cleanly without leaked coroutines."""
    from app.utils.sse_generator import run_heartbeat

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    done = asyncio.Event()
    task = asyncio.create_task(run_heartbeat(queue, done, interval=0.05))
    await asyncio.sleep(0.12)
    done.set()
    await task
    assert task.done()
    assert task.exception() is None


async def test_queue_sse_stream_yields_items():
    """queue_sse_stream yields all items until None sentinel."""
    from app.utils.sse_generator import queue_sse_stream

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    await queue.put("event1")
    await queue.put("event2")
    await queue.put("event3")
    await queue.put(None)

    collected = []
    async for item in queue_sse_stream(queue):
        collected.append(item)

    assert collected == ["event1", "event2", "event3"]


async def test_queue_sse_stream_empty_sentinel():
    """queue_sse_stream with immediate None returns nothing."""
    from app.utils.sse_generator import queue_sse_stream

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    await queue.put(None)

    collected = []
    async for item in queue_sse_stream(queue):
        collected.append(item)

    assert collected == []
