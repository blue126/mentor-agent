"""Integration tests for learning plan — full flow with real DB, mock external services."""

import json
from unittest.mock import patch

from app.services import graph_service


_VALID_PLAN_JSON = json.dumps([
    {"chapter": "1. Introduction", "sections": ["1.1 Getting Started", "1.2 Basic Concepts"]},
    {"chapter": "2. Core Topics", "sections": ["2.1 Topic A", "2.2 Topic B"]},
])


class _FakeSessionContext:
    """Sync-callable that returns an async context manager wrapping a real session."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


@patch("app.tools.learning_plan_tool.get_chat_completion")
@patch("app.tools.learning_plan_tool.search_knowledge_base")
async def test_generate_learning_plan_full_flow(mock_rag, mock_llm, db_session):
    """Full flow: mock RAG + LLM → verify Topic and Concepts written to real DB + NetworkX."""
    graph_service.reset_graph()
    mock_rag.return_value = "Chapter 1: Intro\n1.1 Start\nChapter 2: Core\n2.1 Deep"
    mock_llm.return_value = _VALID_PLAN_JSON

    with patch(
        "app.tools.learning_plan_tool.async_session_factory",
        lambda: _FakeSessionContext(db_session),
    ):
        from app.tools.learning_plan_tool import generate_learning_plan

        result = await generate_learning_plan("Test Integration Book")

    # Verify output format
    assert "Learning Plan: Test Integration Book" in result
    assert "Chapter 1" in result
    assert "Chapter 2" in result
    assert "2 chapters, 4 sections" in result

    # Verify DB state: Topic exists
    topic = await graph_service.get_topic_by_name(db_session, "Test Integration Book")
    assert topic is not None
    assert topic["name"] == "Test Integration Book"

    # Verify DB state: Concepts exist (2 chapters + 4 sections = 6 concepts)
    concepts = await graph_service.get_concepts_by_topic(db_session, topic["id"])
    assert len(concepts) == 6

    concept_names = {c["name"] for c in concepts}
    assert "1. Introduction" in concept_names
    assert "2. Core Topics" in concept_names
    assert "1.1 Getting Started" in concept_names
    assert "2.2 Topic B" in concept_names

    # Verify NetworkX graph has the concepts
    G = graph_service._digraph
    assert G is not None
    assert G.number_of_nodes() >= 6

    graph_service.reset_graph()


async def test_get_learning_plan_with_real_db(db_session):
    """Pre-stored data → verify get_learning_plan returns complete plan."""
    graph_service.reset_graph()

    # Setup: create topic and concepts directly
    topic = await graph_service.add_topic(db_session, "Python Basics")
    await graph_service.add_concept(db_session, "1 Variables", topic_id=topic["id"])
    await graph_service.add_concept(db_session, "1.1 Types", topic_id=topic["id"])
    await graph_service.add_concept(db_session, "1.2 Assignment", topic_id=topic["id"])
    await graph_service.add_concept(db_session, "2 Control Flow", topic_id=topic["id"])
    await graph_service.add_concept(db_session, "2.1 If Statements", topic_id=topic["id"])

    with patch(
        "app.tools.learning_plan_tool.async_session_factory",
        lambda: _FakeSessionContext(db_session),
    ):
        from app.tools.learning_plan_tool import get_learning_plan

        result = await get_learning_plan(topic_name="Python Basics")

    assert "Python Basics" in result
    assert "Variables" in result
    assert "Control Flow" in result

    graph_service.reset_graph()


@patch("app.tools.learning_plan_tool.get_chat_completion")
@patch("app.tools.learning_plan_tool.search_knowledge_base")
async def test_atomic_rollback_no_residual_data(mock_rag, mock_llm, db_session):
    """Partial write failure → DB should have no residual data."""
    graph_service.reset_graph()
    mock_rag.return_value = "Some content"
    mock_llm.return_value = _VALID_PLAN_JSON

    call_count = 0
    original_flush = db_session.flush

    async def _failing_flush(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 5:  # Fail on 5th flush (after topic + 3 concepts)
            raise Exception("Simulated DB error")
        return await original_flush(*args, **kwargs)

    with patch(
        "app.tools.learning_plan_tool.async_session_factory",
        lambda: _FakeSessionContext(db_session),
    ):
        with patch.object(db_session, "flush", side_effect=_failing_flush):
            from app.tools.learning_plan_tool import generate_learning_plan

            result = await generate_learning_plan("Rollback Test Book")

    assert "Error" in result

    # Verify no residual data in DB
    topic = await graph_service.get_topic_by_name(db_session, "Rollback Test Book")
    assert topic is None

    graph_service.reset_graph()
