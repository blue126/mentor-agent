"""Unit tests for SSE event factory functions.

Covers: make_status_event format, make_done_event, make_heartbeat_event.
"""

import json


def test_make_status_event_format():
    """Status event: valid SSE data line with OpenAI chunk structure."""
    from app.utils.sse_generator import make_status_event

    event = make_status_event("💭 Thinking...", "test-model")
    assert event.startswith("data: ")
    assert event.endswith("\n\n")
    payload = json.loads(event[6:-2])  # Strip "data: " and "\n\n"
    assert payload["choices"][0]["delta"]["content"] == "*💭 Thinking...*\n\n"
    assert payload["model"] == "test-model"
    assert payload["object"] == "chat.completion.chunk"


def test_make_status_event_has_id_and_created():
    """Status event chunk contains id and created fields."""
    from app.utils.sse_generator import make_status_event

    event = make_status_event("test", "m")
    payload = json.loads(event[6:-2])
    assert "id" in payload
    assert payload["id"].startswith("chatcmpl-")
    assert "created" in payload
    assert isinstance(payload["created"], int)


def test_make_status_event_tool_name():
    """Status event with tool name renders correctly."""
    from app.utils.sse_generator import make_status_event

    event = make_status_event("🔧 Running echo...", "gpt-4")
    payload = json.loads(event[6:-2])
    assert payload["choices"][0]["delta"]["content"] == "*🔧 Running echo...*\n\n"
    assert payload["model"] == "gpt-4"


def test_make_done_event():
    """Done event: exactly 'data: [DONE]\\n\\n'."""
    from app.utils.sse_generator import make_done_event

    assert make_done_event() == "data: [DONE]\n\n"


def test_make_heartbeat_event():
    """Heartbeat event: SSE comment format '': keepalive\\n\\n'."""
    from app.utils.sse_generator import make_heartbeat_event

    assert make_heartbeat_event() == ": keepalive\n\n"
