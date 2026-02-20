"""Unit tests for list_knowledge_bases tool — normal return, Fail Soft, and formats."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch):
    """Provide mock settings for all tests."""
    s = MagicMock()
    s.openwebui_base_url = "http://open-webui:8080"
    s.openwebui_api_key = "test-key"
    monkeypatch.setattr("app.tools.search_knowledge_base_tool.settings", s)


def _ok_response(data, status_code=200):
    return httpx.Response(
        status_code=status_code,
        json=data,
        request=httpx.Request("GET", "http://test"),
    )


# Test 1: Normal return — list format
async def test_list_normal_list_format():
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    data = [
        {"id": "uuid-1", "name": "Machine Learning Basics"},
        {"id": "uuid-2", "name": "Python Cookbook"},
    ]
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_ok_response(data))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_knowledge_bases()

    assert "- Machine Learning Basics (ID: uuid-1)" in result
    assert "- Python Cookbook (ID: uuid-2)" in result


# Test 2: Normal return — paginated format
async def test_list_normal_paginated_format():
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    data = {
        "items": [
            {"id": "uuid-3", "name": "Deep Learning"},
        ],
        "total": 1,
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_ok_response(data))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_knowledge_bases()

    assert "- Deep Learning (ID: uuid-3)" in result


# Test 3: API unreachable — Fail Soft error string
async def test_list_api_unreachable():
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_knowledge_bases()

    assert "Error:" in result
    assert "unreachable" in result


def _error_response(status_code):
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("GET", "http://test"),
    )


# L6: Timeout — Fail Soft
async def test_list_timeout():
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_knowledge_bases()

    assert "Error:" in result
    assert "unreachable" in result


# L6: 401 authentication failure
async def test_list_401_auth_failure():
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    error_resp = _error_response(401)
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("401", request=error_resp.request, response=error_resp)
    )

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_knowledge_bases()

    assert "authentication failed" in result


# L6: Non-401 HTTP error
async def test_list_500_server_error():
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    error_resp = _error_response(500)
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("500", request=error_resp.request, response=error_resp)
    )

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_knowledge_bases()

    assert "status 500" in result


# L6: Generic exception
async def test_list_generic_exception():
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=RuntimeError("unexpected"))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_knowledge_bases()

    assert "Error: list_knowledge_bases failed:" in result
    assert "unexpected" in result


# L6: Malformed payload (not list or dict with items)
async def test_list_malformed_payload():
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_ok_response("just a string"))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_knowledge_bases()

    assert "unexpected response format" in result


# M2: Empty API key returns early error
async def test_list_empty_api_key(monkeypatch):
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    s = MagicMock()
    s.openwebui_base_url = "http://open-webui:8080"
    s.openwebui_api_key = ""
    monkeypatch.setattr("app.tools.search_knowledge_base_tool.settings", s)

    result = await list_knowledge_bases()
    assert "API key is not configured" in result


# L7: Verify auth header sent correctly
async def test_list_sends_correct_auth_header():
    from app.tools.search_knowledge_base_tool import list_knowledge_bases

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_ok_response([]))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        await list_knowledge_bases()

    call_kwargs = mock_client.get.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"
