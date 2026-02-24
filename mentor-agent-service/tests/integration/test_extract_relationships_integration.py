"""Integration tests for extract_concept_relationships — real DB, mock LLM."""

import json
from unittest.mock import patch

from app.services import graph_service

_VALID_RELATIONSHIPS_JSON = json.dumps([
    {"source": "Functions", "target": "Variables", "type": "prerequisite"},
    {"source": "OOP", "target": "Functions", "type": "prerequisite"},
    {"source": "Variables", "target": "Data Types", "type": "related"},
])


class _FakeSessionContext:
    """Sync-callable returning async context manager wrapping a real session."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


async def _setup_topic_and_concepts(db_session):
    """Create a topic with 4 concepts in the real DB."""
    graph_service.reset_graph()
    topic = await graph_service.add_topic(db_session, "Python Basics")
    await graph_service.add_concept(
        db_session, "Variables", topic_id=topic["id"], definition="Data containers"
    )
    await graph_service.add_concept(
        db_session, "Data Types", topic_id=topic["id"], definition="Types of data"
    )
    await graph_service.add_concept(
        db_session, "Functions", topic_id=topic["id"], definition="Reusable code blocks"
    )
    await graph_service.add_concept(
        db_session, "OOP", topic_id=topic["id"], definition="Object-Oriented Programming"
    )
    await graph_service.load_graph(db_session)
    return topic


@patch("app.tools.extract_relationships_tool.get_chat_completion")
async def test_full_flow_edges_in_db_and_networkx(mock_llm, db_session):
    """Full flow: pre-stored Topic + Concepts → mock LLM → verify edges in DB + NetworkX."""
    topic = await _setup_topic_and_concepts(db_session)
    mock_llm.return_value = _VALID_RELATIONSHIPS_JSON

    with patch(
        "app.tools.extract_relationships_tool.async_session_factory",
        lambda: _FakeSessionContext(db_session),
    ):
        from app.tools.extract_relationships_tool import extract_concept_relationships

        result = await extract_concept_relationships("Python Basics")

    # Verify output format
    assert "Concept Relationships: Python Basics" in result
    assert "New: 3" in result
    assert "Skipped (existing): 0" in result

    # Verify DB state: edges exist
    edges = await graph_service.get_edges_for_concepts(
        db_session, [c["id"] for c in await graph_service.get_concepts_by_topic(db_session, topic["id"])]
    )
    assert len(edges) == 3

    edge_types = {(e["relationship_type"]) for e in edges}
    assert "prerequisite" in edge_types
    assert "related" in edge_types

    # Verify NetworkX graph has edges
    digraph = graph_service._digraph
    assert digraph is not None
    assert digraph.number_of_edges() == 3

    # Verify get_prerequisites works correctly
    concepts = await graph_service.get_concepts_by_topic(db_session, topic["id"])
    concept_by_name = {c["name"]: c for c in concepts}

    # OOP requires Functions
    oop_prereqs = await graph_service.get_prerequisites(db_session, concept_by_name["OOP"]["id"])
    prereq_names = {p["name"] for p in oop_prereqs}
    assert "Functions" in prereq_names

    # Functions requires Variables
    func_prereqs = await graph_service.get_prerequisites(db_session, concept_by_name["Functions"]["id"])
    prereq_names = {p["name"] for p in func_prereqs}
    assert "Variables" in prereq_names

    # Verify get_related_concepts works correctly
    var_related = await graph_service.get_related_concepts(db_session, concept_by_name["Variables"]["id"])
    related_names = {r["name"] for r in var_related}
    assert "Data Types" in related_names

    graph_service.reset_graph()


@patch("app.tools.extract_relationships_tool.get_chat_completion")
async def test_idempotent_no_duplicate_edges(mock_llm, db_session):
    """Execute twice → verify no duplicate edges."""
    await _setup_topic_and_concepts(db_session)
    mock_llm.return_value = _VALID_RELATIONSHIPS_JSON

    with patch(
        "app.tools.extract_relationships_tool.async_session_factory",
        lambda: _FakeSessionContext(db_session),
    ):
        from app.tools.extract_relationships_tool import extract_concept_relationships

        result1 = await extract_concept_relationships("Python Basics")
        assert "New: 3" in result1

        result2 = await extract_concept_relationships("Python Basics")
        assert "New: 0" in result2
        assert "Skipped (existing): 3" in result2

    # Verify exactly 3 edges in DB (not 6)
    concepts = await graph_service.get_concepts_by_topic(db_session, 1)
    edges = await graph_service.get_edges_for_concepts(
        db_session, [c["id"] for c in concepts]
    )
    assert len(edges) == 3

    graph_service.reset_graph()


@patch("app.tools.extract_relationships_tool.get_chat_completion")
async def test_partial_failure_rollback_no_residual(mock_llm, db_session):
    """add_edge fails on Nth call → rollback → no edges in DB."""
    await _setup_topic_and_concepts(db_session)
    mock_llm.return_value = _VALID_RELATIONSHIPS_JSON

    call_count = 0
    original_flush = db_session.flush

    async def _failing_flush(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # First calls from setup are committed; fail on the 2nd flush during edge creation
        if call_count >= 2:
            raise Exception("Simulated DB error")
        return await original_flush(*args, **kwargs)

    with patch(
        "app.tools.extract_relationships_tool.async_session_factory",
        lambda: _FakeSessionContext(db_session),
    ):
        # Patch flush only during the tool call to simulate partial failure
        with patch.object(db_session, "flush", side_effect=_failing_flush):
            from app.tools.extract_relationships_tool import extract_concept_relationships

            result = await extract_concept_relationships("Python Basics")

    assert "Error" in result

    # Verify no residual edges in DB
    concepts = await graph_service.get_concepts_by_topic(db_session, 1)
    edges = await graph_service.get_edges_for_concepts(
        db_session, [c["id"] for c in concepts]
    )
    assert len(edges) == 0

    graph_service.reset_graph()
