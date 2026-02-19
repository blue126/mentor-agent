"""Integration tests for POST /v1/chat/completions endpoint."""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
from tests.test_doubles import MockChunk

from app.main import create_app

_VALID_TOKEN = "test-secret-key"
_MESSAGES_PAYLOAD = {"messages": [{"role": "user", "content": "Hello"}], "model": "test-model"}

async def _mock_stream_response(*chunks: MockChunk) -> AsyncIterator[MockChunk]:
    for chunk in chunks:
        yield chunk


def _build_client():
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


async def test_streaming_chat_returns_sse_format():
    """Full streaming request should return valid SSE events ending with [DONE]."""
    ac, app = _build_client()

    mock_stream = _mock_stream_response(MockChunk("Hello"), MockChunk(" world", "stop"))

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(return_value=mock_stream)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={**_MESSAGES_PAYLOAD, "stream": True},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    lines = [line for line in resp.text.split("\n\n") if line.strip()]
    # Last should be [DONE]
    assert lines[-1].strip() == "data: [DONE]"
    # All others should be valid JSON
    for line in lines[:-1]:
        payload = line.replace("data: ", "", 1)
        parsed = json.loads(payload)
        assert "choices" in parsed


async def test_non_streaming_chat_returns_json():
    """Non-streaming request should return a JSON completion response."""
    ac, app = _build_client()

    mock_response = type(
        "Response",
        (),
        {
            "choices": [
                type(
                    "Choice",
                    (),
                    {
                        "message": type("Msg", (), {"role": "assistant", "content": "Hi there!"})(),
                        "finish_reason": "stop",
                    },
                )()
            ],
            "usage": type("Usage", (), {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8})(),
            "model": "test-model",
        },
    )()

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
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "Hi there!"
    assert data["usage"]["total_tokens"] == 8


async def test_bad_token_returns_401():
    """Invalid Bearer token should return 401 for the chat endpoint."""
    ac, _ = _build_client()
    async with ac:
        resp = await ac.post(
            "/v1/chat/completions",
            json=_MESSAGES_PAYLOAD,
            headers={"Authorization": "Bearer bad-token"},
        )
    assert resp.status_code == 401


async def test_missing_token_returns_401():
    """No Authorization header should return 401."""
    ac, _ = _build_client()
    async with ac:
        resp = await ac.post("/v1/chat/completions", json=_MESSAGES_PAYLOAD)
    assert resp.status_code == 401


async def test_llm_failure_returns_502():
    """When LiteLLM is unreachable, streaming should return 502 error response."""
    ac, app = _build_client()

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=Exception("Connection refused"))

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={**_MESSAGES_PAYLOAD, "stream": True},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 502
    data = resp.json()
    assert "error" in data
    assert "proxy_error" in data["error"]["type"]


async def test_non_streaming_empty_choices_returns_502():
    """Upstream empty choices should fail soft with 502, not crash."""
    ac, _ = _build_client()

    mock_response = type("Response", (), {"choices": [], "usage": None, "model": "test-model"})()

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hello"}], "stream": False},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 502
    data = resp.json()
    assert data["error"]["type"] == "proxy_error"


async def test_non_streaming_null_usage_returns_200():
    """Non-streaming response with usage=None should return 200 with zeroed usage, not crash."""
    ac, _ = _build_client()

    mock_response = type(
        "Response",
        (),
        {
            "choices": [
                type(
                    "Choice",
                    (),
                    {
                        "message": type("Msg", (), {"role": "assistant", "content": "Hi"})(),
                        "finish_reason": "stop",
                    },
                )()
            ],
            "usage": None,
            "model": "test-model",
        },
    )()

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hello"}], "stream": False},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["usage"]["prompt_tokens"] == 0
    assert data["usage"]["completion_tokens"] == 0
    assert data["usage"]["total_tokens"] == 0


async def test_invalid_role_returns_422():
    """Invalid chat role should be rejected at schema validation boundary."""
    ac, _ = _build_client()

    with patch("app.dependencies.settings") as mock_dep_settings:
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "not-a-valid-role", "content": "Hello"}],
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 422
