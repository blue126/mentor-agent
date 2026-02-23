"""Unit tests for list_collections tool — normal return, Fail Soft, file listing, and formats."""

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


# ---------------------------------------------------------------------------
# Normal return tests (list + /files)
# ---------------------------------------------------------------------------


async def test_list_normal_list_format():
    from app.tools.search_knowledge_base_tool import list_collections

    list_data = [
        {"id": "uuid-1", "name": "Machine Learning Basics"},
        {"id": "uuid-2", "name": "Python Cookbook"},
    ]
    files_1 = {"items": [{"filename": "ml-basics.pdf"}]}
    files_2 = {"items": [{"filename": "python-cookbook.pdf"}]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(
        side_effect=[_ok_response(list_data), _ok_response(files_1), _ok_response(files_2)]
    )

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "- Machine Learning Basics" in result
    assert "- Python Cookbook" in result
    assert "• ml-basics.pdf" in result
    assert "• python-cookbook.pdf" in result
    assert "uuid" not in result  # UUIDs should be hidden from LLM


async def test_list_normal_paginated_format():
    from app.tools.search_knowledge_base_tool import list_collections

    list_data = {
        "items": [
            {"id": "uuid-3", "name": "Deep Learning"},
        ],
        "total": 1,
    }
    files = {"items": [{"filename": "deep-learning.pdf"}]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[_ok_response(list_data), _ok_response(files)])

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "- Deep Learning" in result
    assert "• deep-learning.pdf" in result
    assert "uuid" not in result


async def test_list_files_plain_list_format():
    """Files endpoint returns a plain list (not paginated dict)."""
    from app.tools.search_knowledge_base_tool import list_collections

    list_data = [{"id": "uuid-1", "name": "My Collection"}]
    files = [{"filename": "doc-a.pdf"}, {"filename": "doc-b.pdf"}]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[_ok_response(list_data), _ok_response(files)])

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "- My Collection (2 documents)" in result
    assert "• doc-a.pdf" in result
    assert "• doc-b.pdf" in result


# ---------------------------------------------------------------------------
# Multi-document collection
# ---------------------------------------------------------------------------


async def test_list_with_multiple_files():
    """Collection with multiple documents shows all filenames."""
    from app.tools.search_knowledge_base_tool import list_collections

    list_data = [{"id": "uuid-ai", "name": "AI-Assisted Programming"}]
    files = {"items": [
        {"filename": "AI-Assisted-Programming.pdf"},
        {"filename": "The-Pragmatic-Programmer.pdf"},
        {"filename": "Tidy-First.pdf"},
        {"filename": "Pro-Git.pdf"},
        {"filename": "A-Philosophy-of-Software-Design.pdf"},
    ]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[_ok_response(list_data), _ok_response(files)])

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "AI-Assisted Programming (5 documents)" in result
    assert "• AI-Assisted-Programming.pdf" in result
    assert "• The-Pragmatic-Programmer.pdf" in result
    assert "• Pro-Git.pdf" in result
    assert "Available collections:" in result


# ---------------------------------------------------------------------------
# Truncation — files exceeding _MAX_FILES_DISPLAY
# ---------------------------------------------------------------------------


async def test_list_truncates_long_file_lists():
    """Collections with >10 files are truncated with '...and N more'."""
    from app.tools.search_knowledge_base_tool import list_collections

    list_data = [{"id": "uuid-big", "name": "Big Collection"}]
    files = {"items": [{"filename": f"book-{i:02d}.pdf"} for i in range(15)]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[_ok_response(list_data), _ok_response(files)])

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "Big Collection (15 documents)" in result
    assert "• book-00.pdf" in result
    assert "• book-09.pdf" in result
    assert "book-10.pdf" not in result  # beyond limit
    assert "...and 5 more" in result


# ---------------------------------------------------------------------------
# Fail Soft: files endpoint failures degrade gracefully
# ---------------------------------------------------------------------------


async def test_list_files_failure_degrades_gracefully():
    """When files API fails, still shows collection name without files."""
    from app.tools.search_knowledge_base_tool import list_collections

    list_data = [{"id": "uuid-1", "name": "My Collection"}]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    # First call: list succeeds; second call: files endpoint fails
    mock_client.get = AsyncMock(
        side_effect=[_ok_response(list_data), httpx.ConnectError("connection refused")]
    )

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "- My Collection" in result
    assert "documents" not in result  # no file count since files endpoint failed
    assert "Error" not in result  # no error bubbled up


async def test_list_files_unexpected_format():
    """Files endpoint returns unexpected format — degrades to name-only."""
    from app.tools.search_knowledge_base_tool import list_collections

    list_data = [{"id": "uuid-1", "name": "Weird Collection"}]
    # Unexpected format: string instead of list/dict
    files_resp = "not json array"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[_ok_response(list_data), _ok_response(files_resp)])

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "- Weird Collection" in result
    assert "documents" not in result  # no file count
    assert "•" not in result  # no file bullets


async def test_list_files_empty():
    """Collection with empty files array shows name without file list."""
    from app.tools.search_knowledge_base_tool import list_collections

    list_data = [{"id": "uuid-1", "name": "Empty Collection"}]
    files = {"items": []}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[_ok_response(list_data), _ok_response(files)])

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "- Empty Collection" in result
    assert "documents" not in result


# ---------------------------------------------------------------------------
# Filename extraction from different response structures
# ---------------------------------------------------------------------------


async def test_list_extracts_filenames_from_alternate_fields():
    """Extracts filenames from 'name' field when 'filename' is absent."""
    from app.tools.search_knowledge_base_tool import list_collections

    list_data = [{"id": "uuid-1", "name": "Alt Format"}]
    files = {"items": [
        {"name": "via-name-field.pdf"},
        {"meta": {"name": "via-meta-name.pdf"}},
    ]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=[_ok_response(list_data), _ok_response(files)])

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "• via-name-field.pdf" in result
    assert "• via-meta-name.pdf" in result


# ---------------------------------------------------------------------------
# Existing Fail Soft tests (list API level — no files calls reached)
# ---------------------------------------------------------------------------


async def test_list_api_unreachable():
    from app.tools.search_knowledge_base_tool import list_collections

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "Error:" in result
    assert "unreachable" in result


def _error_response(status_code):
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("GET", "http://test"),
    )


async def test_list_timeout():
    from app.tools.search_knowledge_base_tool import list_collections

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "Error:" in result
    assert "unreachable" in result


async def test_list_401_auth_failure():
    from app.tools.search_knowledge_base_tool import list_collections

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    error_resp = _error_response(401)
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("401", request=error_resp.request, response=error_resp)
    )

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "authentication failed" in result


async def test_list_500_server_error():
    from app.tools.search_knowledge_base_tool import list_collections

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    error_resp = _error_response(500)
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("500", request=error_resp.request, response=error_resp)
    )

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "status 500" in result


async def test_list_generic_exception():
    from app.tools.search_knowledge_base_tool import list_collections

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=RuntimeError("unexpected"))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "Error: list_collections failed:" in result
    assert "unexpected" in result


async def test_list_malformed_payload():
    from app.tools.search_knowledge_base_tool import list_collections

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_ok_response("just a string"))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        result = await list_collections()

    assert "unexpected response format" in result


async def test_list_empty_api_key(monkeypatch):
    from app.tools.search_knowledge_base_tool import list_collections

    s = MagicMock()
    s.openwebui_base_url = "http://open-webui:8080"
    s.openwebui_api_key = ""
    monkeypatch.setattr("app.tools.search_knowledge_base_tool.settings", s)

    result = await list_collections()
    assert "API key is not configured" in result


async def test_list_sends_correct_auth_header():
    from app.tools.search_knowledge_base_tool import list_collections

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_ok_response([]))

    with patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_client):
        await list_collections()

    call_kwargs = mock_client.get.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"
