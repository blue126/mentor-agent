"""Integration tests for knowledge graph — full flow through service + repository + DB."""

import pytest

from app.services import graph_service


@pytest.fixture(autouse=True)
def _reset_graph():
    """Reset the module-level graph singleton before each test."""
    graph_service.reset_graph()
    yield
    graph_service.reset_graph()


async def test_full_flow_topic_concepts_edges_queries(db_session):
    """Full flow: create topic → add concepts → add edges → query prerequisites + related."""
    # Create topic
    topic = await graph_service.add_topic(db_session, "Machine Learning", description="ML fundamentals")
    assert topic["name"] == "Machine Learning"

    # Add concepts
    lr = await graph_service.add_concept(db_session, "Linear Regression", topic_id=topic["id"], difficulty="beginner")
    stats = await graph_service.add_concept(db_session, "Statistics", topic_id=topic["id"], difficulty="beginner")
    calculus = await graph_service.add_concept(db_session, "Calculus", difficulty="intermediate")
    nn = await graph_service.add_concept(db_session, "Neural Networks", topic_id=topic["id"], difficulty="advanced")

    # Add edges: LR depends on Stats and Calculus; NN related to LR
    await graph_service.add_edge(db_session, lr["id"], stats["id"], "prerequisite")
    await graph_service.add_edge(db_session, lr["id"], calculus["id"], "prerequisite")
    await graph_service.add_edge(db_session, nn["id"], lr["id"], "related")

    # Query prerequisites of Linear Regression → should return Stats + Calculus
    prereqs = await graph_service.get_prerequisites(db_session, lr["id"])
    prereq_names = {p["name"] for p in prereqs}
    assert prereq_names == {"Statistics", "Calculus"}

    # Query related concepts of Linear Regression → should return Neural Networks (incoming related)
    related = await graph_service.get_related_concepts(db_session, lr["id"])
    related_names = {r["name"] for r in related}
    assert related_names == {"Neural Networks"}

    # Summary
    summary = await graph_service.get_concept_graph_summary(db_session)
    assert "4 concepts" in summary
    assert "3 edges" in summary
    assert "Machine Learning" in summary


async def test_persistence_across_graph_reload(db_session):
    """Data survives reset_graph + load_graph (proves DB persistence)."""
    a = await graph_service.add_concept(db_session, "A", definition="First concept")
    b = await graph_service.add_concept(db_session, "B", definition="Second concept")
    await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")

    # Reset in-memory graph and reload from DB
    graph_service.reset_graph()
    await graph_service.load_graph(db_session)

    # Verify MultiDiGraph matches what was persisted
    G = graph_service._digraph
    assert G is not None
    assert a["id"] in G.nodes
    assert b["id"] in G.nodes
    assert G.nodes[a["id"]]["name"] == "A"
    assert G.nodes[b["id"]]["name"] == "B"
    assert G.has_edge(a["id"], b["id"])

    # Verify query still works after reload
    prereqs = await graph_service.get_prerequisites(db_session, a["id"])
    assert len(prereqs) == 1
    assert prereqs[0]["name"] == "B"
