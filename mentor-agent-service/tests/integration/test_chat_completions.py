"""Integration tests for POST /v1/chat/completions endpoint."""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.config import ProviderConfig
from app.main import create_app
from tests.test_doubles import MockChunk

_VALID_TOKEN = "test-secret-key"
_MESSAGES_PAYLOAD = {"messages": [{"role": "user", "content": "Hello"}], "model": "test-model"}

_TEST_PROVIDER = ProviderConfig(
    id="test-model",
    display_name="Test Model",
    base_url="http://litellm",
    api_key="test-key",
    model="openai/test-model",
)


async def _mock_stream_response(*chunks: MockChunk) -> AsyncIterator[MockChunk]:
    for chunk in chunks:
        yield chunk


def _build_client():
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


def _make_text_response(content="Hi there!", finish_reason="stop", model="test-model", usage=None):
    """Build a mock non-streaming LLM response (no tool_calls)."""
    if usage is None:
        usage = type("Usage", (), {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8})()
    return type(
        "Response",
        (),
        {
            "choices": [
                type(
                    "Choice",
                    (),
                    {
                        "message": type("Msg", (), {"role": "assistant", "content": content, "tool_calls": None})(),
                        "finish_reason": finish_reason,
                    },
                )()
            ],
            "usage": usage,
            "model": model,
        },
    )()


def _make_stream_aware_mock(non_stream_response, stream_response):
    """Create an acompletion mock that returns different values for stream=True vs stream=False."""
    async def _side_effect(**kwargs):
        if kwargs.get("stream"):
            return stream_response
        return non_stream_response
    return _side_effect


def _patch_resolve_provider():
    """Patch resolve_provider so 'test-model' maps to _TEST_PROVIDER."""
    def _mock_resolve(model_id):
        if not model_id or model_id == "test-model":
            return _TEST_PROVIDER
        return None
    return patch("app.routers.chat.resolve_provider", side_effect=_mock_resolve)


def _patch_get_providers():
    """Patch get_providers to return _TEST_PROVIDER."""
    return patch("app.routers.chat.get_providers", return_value=[_TEST_PROVIDER])


async def test_streaming_chat_returns_sse_format():
    """Full streaming request should return valid SSE events ending with [DONE]."""
    ac, app = _build_client()

    text_resp = _make_text_response("Hello world")

    async def _side_effect(**kwargs):
        return _mock_stream_response(MockChunk("Hello"), MockChunk(" world", "stop"))

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.services.agent_service.litellm") as mock_agent_litellm,
        _patch_resolve_provider(),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=_side_effect)
        mock_agent_litellm.stream_chunk_builder = MagicMock(
            return_value=text_resp
        )

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={**_MESSAGES_PAYLOAD, "stream": True},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    lines = [line for line in resp.text.split("\n\n") if line.strip() and line.startswith("data:")]
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

    mock_response = _make_text_response("Hi there!")

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        _patch_resolve_provider(),
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


async def test_llm_failure_streaming_returns_error_in_sse():
    """When LiteLLM is unreachable, streaming should return SSE with error status + [DONE]."""
    ac, app = _build_client()

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        _patch_resolve_provider(),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=Exception("Connection refused"))

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={**_MESSAGES_PAYLOAD, "stream": True},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    # Streaming path now returns 200 with error as SSE status event
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # Should contain error text and [DONE]
    assert "Connection refused" in resp.text or "unavailable" in resp.text.lower()
    assert "data: [DONE]" in resp.text


async def test_non_streaming_empty_choices_returns_502():
    """Upstream empty choices should fail soft with 502, not crash."""
    ac, _ = _build_client()

    mock_response = type("Response", (), {"choices": [], "usage": None, "model": "test-model"})()

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        _patch_resolve_provider(),
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

    mock_response = _make_text_response("Hi", usage=None)
    # Override usage to None after creation
    mock_response.usage = None

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        _patch_resolve_provider(),
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


# ---------------------------------------------------------------------------
# New tests for double active provider (Story 1.6)
# ---------------------------------------------------------------------------

_ALT_PROVIDER = ProviderConfig(
    id="mentor-api",
    display_name="Mentor (API)",
    base_url="https://api.anthropic.com",
    api_key="sk-ant-xxx",
    model="claude-sonnet-4-6",
)


async def test_list_models_returns_two_when_double_active():
    """AC #1: /v1/models returns two models when double active configured."""
    ac, _ = _build_client()

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.routers.chat.get_providers", return_value=[_TEST_PROVIDER, _ALT_PROVIDER]),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        async with ac:
            resp = await ac.get(
                "/v1/models",
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) == 2
    ids = [m["id"] for m in data["data"]]
    assert "test-model" in ids
    assert "mentor-api" in ids
    owned = {m["id"]: m["owned_by"] for m in data["data"]}
    assert owned["test-model"] == "Test Model"
    assert owned["mentor-api"] == "Mentor (API)"


async def test_chat_completions_routes_to_correct_provider():
    """AC #2: chat completions routes to correct provider based on model parameter."""
    ac, _ = _build_client()

    mock_response = _make_text_response("API response")

    def _mock_resolve(model_id):
        if model_id == "mentor-api":
            return _ALT_PROVIDER
        if not model_id or model_id == "test-model":
            return _TEST_PROVIDER
        return None

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.routers.chat.resolve_provider", side_effect=_mock_resolve),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hello"}], "model": "mentor-api", "stream": False},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    # Verify the acompletion was called with the alt provider's config
    call_kwargs = mock_litellm.acompletion.call_args.kwargs
    assert call_kwargs["api_base"] == "https://api.anthropic.com"
    assert call_kwargs["api_key"] == "sk-ant-xxx"
    assert call_kwargs["model"] == "claude-sonnet-4-6"


async def test_chat_completions_unknown_model_returns_404():
    """AC #8: chat completions with unknown model ID returns 404."""
    ac, _ = _build_client()

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.routers.chat.resolve_provider", return_value=None),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hello"}], "model": "nonexistent", "stream": False},
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["type"] == "not_found_error"
    assert "nonexistent" in data["error"]["message"]


async def test_get_model_returns_200_for_configured_provider():
    """AC #8: GET /v1/models/{model_id} returns 200 for configured provider."""
    ac, _ = _build_client()

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.routers.chat.resolve_provider", return_value=_TEST_PROVIDER),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN

        async with ac:
            resp = await ac.get(
                "/v1/models/test-model",
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "test-model"
    assert data["owned_by"] == "Test Model"


async def test_get_model_returns_404_for_unknown():
    """AC #8: GET /v1/models/{model_id} returns 404 for unknown IDs."""
    ac, _ = _build_client()

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.routers.chat.resolve_provider", return_value=None),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN

        async with ac:
            resp = await ac.get(
                "/v1/models/nonexistent",
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["type"] == "not_found_error"
