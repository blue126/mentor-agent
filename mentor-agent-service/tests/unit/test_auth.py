"""Unit tests for Bearer Token authentication dependency."""

from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_missing_token_returns_401():
    """Missing Authorization header should return 401 Unauthorized."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


async def test_invalid_token_returns_401():
    """Wrong Bearer token should return 401 Unauthorized."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


async def test_valid_token_passes_through():
    """Correct Bearer token should not return 401."""
    app = create_app()
    transport = ASGITransport(app=app)
    with (
        patch("app.dependencies.settings") as mock_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
    ):
        mock_settings.agent_api_key = "test-secret-key"
        mock_litellm.acompletion = AsyncMock(side_effect=Exception("mocked"))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": "Bearer test-secret-key"},
            )
    # Auth passed → request reaches router → LLM mock fails → Fail Soft
    # Streaming path (default) returns 200 SSE with error; non-streaming returns 502
    # Default stream=True, so error is inside SSE stream (200)
    assert resp.status_code == 200


async def test_health_endpoint_no_auth_required():
    """Health endpoint should remain accessible without authentication."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
