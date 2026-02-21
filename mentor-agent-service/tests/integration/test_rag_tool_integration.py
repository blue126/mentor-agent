"""Integration tests for RAG tools — registry, schema, and agent loop integration."""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.tools import registry
from tests.test_doubles import MockChunk

_VALID_TOKEN = "test-secret-key"


# Test 1: search_knowledge_base registered in registry
def test_search_knowledge_base_registered():
    tool = registry.get_tool("search_knowledge_base")
    assert tool is not None


# Test 2: list_knowledge_bases registered in registry
def test_list_knowledge_bases_registered():
    tool = registry.get_tool("list_knowledge_bases")
    assert tool is not None


# Test 3: Schema validation — both tools have complete schemas
def test_rag_tools_schemas_complete():
    schemas = registry.get_all_schemas()
    tool_names = [s["function"]["name"] for s in schemas]
    assert "search_knowledge_base" in tool_names
    assert "list_knowledge_bases" in tool_names

    # Validate search_knowledge_base schema
    search_schema = next(s for s in schemas if s["function"]["name"] == "search_knowledge_base")
    assert "query" in search_schema["function"]["parameters"]["properties"]
    assert "collection_names" in search_schema["function"]["parameters"]["properties"]
    assert "k" in search_schema["function"]["parameters"]["properties"]
    assert search_schema["function"]["parameters"]["required"] == ["query"]

    # Validate list_knowledge_bases schema
    list_schema = next(s for s in schemas if s["function"]["name"] == "list_knowledge_bases")
    assert list_schema["function"]["parameters"]["required"] == []


# Test 4: Agent loop integration — mock LLM calls search_knowledge_base, mock Open WebUI returns results
async def test_agent_loop_rag_tool_use():
    """Full flow: LLM returns tool_use for search_knowledge_base → tool executes → result injected → LLM final answer."""
    ac = AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
    )

    tool_args = json.dumps({
        "query": "what is machine learning",
        "collection_names": ["col-1"],
        "k": 2,
    })
    tool_resp = _make_tool_call_response("search_knowledge_base", tool_args, "toolu_rag1")
    text_resp = _make_text_response("Based on your documents, machine learning is...")

    call_count = 0

    async def _llm_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_stream(MockChunk(None))  # tool_call round
        return _mock_stream(
            MockChunk("Based on your documents"),
            MockChunk(", machine learning is...", "stop"),
        )

    # Mock Open WebUI API response
    rag_response_data = {
        "documents": [["ML is a subset of AI that learns from data."]],
        "metadatas": [[{"name": "ml-basics.pdf"}]],
        "distances": [[0.95]],
    }

    import httpx

    mock_rag_response = httpx.Response(
        status_code=200,
        json=rag_response_data,
        request=httpx.Request("POST", "http://test"),
    )

    mock_httpx_client = AsyncMock()
    mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
    mock_httpx_client.__aexit__ = AsyncMock(return_value=False)
    mock_httpx_client.post = AsyncMock(return_value=mock_rag_response)

    with (
        patch("app.dependencies.settings") as mock_dep_settings,
        patch("app.services.llm_service.litellm") as mock_litellm,
        patch("app.services.agent_service.litellm") as mock_agent_litellm,
        patch("app.tools.search_knowledge_base_tool.httpx.AsyncClient", return_value=mock_httpx_client),
    ):
        mock_dep_settings.agent_api_key = _VALID_TOKEN
        mock_litellm.acompletion = AsyncMock(side_effect=_llm_side_effect)
        mock_agent_litellm.stream_chunk_builder = MagicMock(
            side_effect=[tool_resp, text_resp]
        )

        async with ac:
            resp = await ac.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Search knowledge base for machine learning"}],
                    "model": "test-model",
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    # Verify the tool was called (httpx post was invoked)
    mock_httpx_client.post.assert_called_once()

    # Verify SSE stream contains content
    lines = [line for line in resp.text.split("\n\n") if line.strip() and line.startswith("data:")]
    assert lines[-1].strip() == "data: [DONE]"

    data_chunks = []
    for line in lines[:-1]:
        payload = line.replace("data: ", "", 1)
        try:
            parsed = json.loads(payload)
            if "choices" in parsed:
                data_chunks.append(parsed)
        except json.JSONDecodeError:
            continue  # skip status events
    assert len(data_chunks) >= 1


# --- Helpers (same pattern as test_tool_use_flow.py) ---

async def _mock_stream(*chunks: MockChunk) -> AsyncIterator[MockChunk]:
    for chunk in chunks:
        yield chunk


def _make_tool_call_response(tool_name, tool_args, tool_id):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].finish_reason = "tool_calls"

    tool_call = MagicMock()
    tool_call.id = tool_id
    tool_call.function.name = tool_name
    tool_call.function.arguments = tool_args

    response.choices[0].message = MagicMock()
    response.choices[0].message.content = None
    response.choices[0].message.tool_calls = [tool_call]
    response.choices[0].message.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": tool_id,
            "type": "function",
            "function": {"name": tool_name, "arguments": tool_args},
        }],
    }
    return response


def _make_text_response(content="Done"):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = None
    response.choices[0].finish_reason = "stop"
    response.choices[0].message.role = "assistant"
    response.usage = MagicMock()
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    response.usage.total_tokens = 15
    response.model = "test-model"
    return response
