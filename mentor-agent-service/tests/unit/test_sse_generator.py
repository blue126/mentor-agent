"""Unit tests for SSE generator utility."""

import json

from tests.test_doubles import MockChunk

from app.utils.sse_generator import sse_stream


async def _mock_stream(*chunks: MockChunk):
    for chunk in chunks:
        yield chunk


async def test_sse_format_output():
    """SSE lines must follow 'data: {json}\\n\\n' format."""
    stream = _mock_stream(MockChunk("Hello"), MockChunk(" world", "stop"))
    lines = [line async for line in sse_stream(stream)]

    # Each line except [DONE] should be valid JSON after "data: " prefix
    for line in lines[:-1]:
        assert line.startswith("data: ")
        assert line.endswith("\n\n")
        payload = line[len("data: ") :].strip()
        parsed = json.loads(payload)
        assert "choices" in parsed


async def test_done_terminator():
    """Stream must end with 'data: [DONE]\\n\\n'."""
    stream = _mock_stream(MockChunk("Hi", "stop"))
    lines = [line async for line in sse_stream(stream)]
    assert lines[-1] == "data: [DONE]\n\n"


async def test_error_handling_mid_stream():
    """Mid-stream errors should yield an error event then [DONE], not crash."""

    async def _error_stream():
        yield MockChunk("partial")
        raise RuntimeError("connection lost")

    lines = [line async for line in sse_stream(_error_stream())]
    # Should have: partial chunk, error event, [DONE]
    assert len(lines) >= 2
    assert lines[-1] == "data: [DONE]\n\n"
    # Error event should contain error info
    error_line = lines[-2]
    assert "error" in error_line.lower() or "error" in json.loads(error_line[len("data: ") :].strip()).get(
        "choices", [{}]
    )[0].get("delta", {}).get("content", "").lower()
