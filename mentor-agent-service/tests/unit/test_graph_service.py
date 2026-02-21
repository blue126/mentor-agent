"""Unit tests for graph_service — NetworkX MultiDiGraph with real in-memory SQLite."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.services import graph_service


@pytest.fixture(autouse=True)
def _reset_graph():
    """Reset the module-level graph singleton before each test."""
    graph_service.reset_graph()
    yield
    graph_service.reset_graph()


class TestGraphService:
    """Tests using real db_session + real NetworkX."""

    async def test_add_concept_and_load_graph(self, db_session):
        result = await graph_service.add_concept(db_session, "Decorator", definition="A wrapper")
        assert result["name"] == "Decorator"

        graph_service.reset_graph()
        await graph_service.load_graph(db_session)

        G = graph_service._digraph
        assert G is not None
        assert result["id"] in G.nodes
        assert G.nodes[result["id"]]["name"] == "Decorator"

    async def test_add_edge(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        edge = await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")

        assert edge["source_concept_id"] == a["id"]
        assert edge["target_concept_id"] == b["id"]
        assert edge["relationship_type"] == "prerequisite"

        G = graph_service._digraph
        assert G.has_edge(a["id"], b["id"])

    async def test_get_prerequisites(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        c = await graph_service.add_concept(db_session, "C")
        await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")
        await graph_service.add_edge(db_session, a["id"], c["id"], "prerequisite")

        prereqs = await graph_service.get_prerequisites(db_session, a["id"])
        prereq_ids = {p["id"] for p in prereqs}
        assert prereq_ids == {b["id"], c["id"]}

    async def test_get_related_concepts_bidirectional(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        d = await graph_service.add_concept(db_session, "D")
        e = await graph_service.add_concept(db_session, "E")
        # A→D outgoing related
        await graph_service.add_edge(db_session, a["id"], d["id"], "related")
        # E→A incoming related
        await graph_service.add_edge(db_session, e["id"], a["id"], "related")

        related = await graph_service.get_related_concepts(db_session, a["id"])
        related_ids = {r["id"] for r in related}
        assert related_ids == {d["id"], e["id"]}

    async def test_get_concept_graph_summary(self, db_session):
        topic = await graph_service.add_topic(db_session, "ML")
        await graph_service.add_concept(db_session, "LinearReg", topic_id=topic["id"])
        await graph_service.add_concept(db_session, "LogisticReg", topic_id=topic["id"])

        summary = await graph_service.get_concept_graph_summary(db_session)
        assert "2 concepts" in summary
        assert "0 edges" in summary
        assert "ML" in summary

    async def test_dual_write_consistency(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")

        # Reset and reload from DB
        graph_service.reset_graph()
        await graph_service.load_graph(db_session)

        G = graph_service._digraph
        assert a["id"] in G.nodes
        assert b["id"] in G.nodes
        assert G.has_edge(a["id"], b["id"])

    async def test_add_topic(self, db_session):
        result = await graph_service.add_topic(db_session, "Python", description="Python programming")
        assert result["name"] == "Python"
        assert isinstance(result["id"], int)

    async def test_get_prerequisites_empty(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        prereqs = await graph_service.get_prerequisites(db_session, a["id"])
        assert prereqs == []

    async def test_get_related_concepts_empty(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        related = await graph_service.get_related_concepts(db_session, a["id"])
        assert related == []

    async def test_multiple_prerequisites(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        c = await graph_service.add_concept(db_session, "C")
        await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")
        await graph_service.add_edge(db_session, a["id"], c["id"], "prerequisite")

        prereqs = await graph_service.get_prerequisites(db_session, a["id"])
        assert len(prereqs) == 2
        prereq_ids = {p["id"] for p in prereqs}
        assert prereq_ids == {b["id"], c["id"]}

    async def test_invalid_relationship_type(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        with pytest.raises(ValueError, match="Invalid relationship_type"):
            await graph_service.add_edge(db_session, a["id"], b["id"], "unknown")

    async def test_nonexistent_source_concept(self, db_session):
        b = await graph_service.add_concept(db_session, "B")
        with pytest.raises(ValueError, match="Source concept 9999 does not exist"):
            await graph_service.add_edge(db_session, 9999, b["id"], "prerequisite")

    async def test_same_node_pair_multiple_relationship_types(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")
        await graph_service.add_edge(db_session, a["id"], b["id"], "related")

        G = graph_service._digraph
        # MultiDiGraph should have 2 edges between A and B
        assert G.number_of_edges(a["id"], b["id"]) == 2

    async def test_duplicate_edge_raises(self, db_session):
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")
        with pytest.raises(IntegrityError):
            await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")

    # --- Story 2.3: Query helper functions ---

    async def test_get_topic_by_name_found(self, db_session):
        await graph_service.add_topic(db_session, "Python", description="Learn Python")
        result = await graph_service.get_topic_by_name(db_session, "Python")
        assert result is not None
        assert result["name"] == "Python"
        assert result["description"] == "Learn Python"

    async def test_get_topic_by_name_not_found(self, db_session):
        result = await graph_service.get_topic_by_name(db_session, "NonExistent")
        assert result is None

    async def test_get_all_topics_empty(self, db_session):
        result = await graph_service.get_all_topics(db_session)
        assert result == []

    async def test_get_all_topics_multiple(self, db_session):
        await graph_service.add_topic(db_session, "Python")
        await graph_service.add_topic(db_session, "JavaScript")
        result = await graph_service.get_all_topics(db_session)
        assert len(result) == 2
        names = {t["name"] for t in result}
        assert names == {"Python", "JavaScript"}

    async def test_get_concepts_by_topic_found(self, db_session):
        topic = await graph_service.add_topic(db_session, "ML")
        await graph_service.add_concept(db_session, "LinearReg", topic_id=topic["id"])
        await graph_service.add_concept(db_session, "LogisticReg", topic_id=topic["id"])
        await graph_service.add_concept(db_session, "Unrelated")

        result = await graph_service.get_concepts_by_topic(db_session, topic["id"])
        assert len(result) == 2
        names = {c["name"] for c in result}
        assert names == {"LinearReg", "LogisticReg"}

    async def test_get_concepts_by_topic_empty(self, db_session):
        topic = await graph_service.add_topic(db_session, "Empty Topic")
        result = await graph_service.get_concepts_by_topic(db_session, topic["id"])
        assert result == []

    # --- Story 2.3: auto_commit parameter ---

    async def test_add_topic_auto_commit_true_default(self, db_session):
        """Default auto_commit=True should commit immediately."""
        result = await graph_service.add_topic(db_session, "Committed")
        assert isinstance(result["id"], int)
        # Verify persisted by querying
        found = await graph_service.get_topic_by_name(db_session, "Committed")
        assert found is not None

    async def test_add_topic_auto_commit_false(self, db_session):
        """auto_commit=False should flush but not commit; rollback discards."""
        result = await graph_service.add_topic(db_session, "Uncommitted", auto_commit=False)
        assert isinstance(result["id"], int)
        # Rollback should discard
        await db_session.rollback()
        found = await graph_service.get_topic_by_name(db_session, "Uncommitted")
        assert found is None

    async def test_add_concept_auto_commit_false_rollback(self, db_session):
        """auto_commit=False for concept; rollback discards and no graph update."""
        topic = await graph_service.add_topic(db_session, "T1")
        result = await graph_service.add_concept(
            db_session, "C1", topic_id=topic["id"], auto_commit=False
        )
        assert isinstance(result["id"], int)
        # Rollback
        await db_session.rollback()
        # Concept should not exist in DB
        from app.repositories.graph_repo import GraphRepository
        repo = GraphRepository(db_session)
        found = await repo.get_concept_by_name("C1")
        assert found is None

    async def test_add_concept_auto_commit_false_then_commit(self, db_session):
        """auto_commit=False then manual commit should persist."""
        topic = await graph_service.add_topic(db_session, "T1")
        c1 = await graph_service.add_concept(
            db_session, "C1", topic_id=topic["id"], auto_commit=False
        )
        c2 = await graph_service.add_concept(
            db_session, "C2", topic_id=topic["id"], auto_commit=False
        )
        await db_session.commit()
        await graph_service.load_graph(db_session)

        concepts = await graph_service.get_concepts_by_topic(db_session, topic["id"])
        assert len(concepts) == 2
        names = {c["name"] for c in concepts}
        assert names == {"C1", "C2"}

    # --- Story 2.4: get_edges_for_concepts ---

    async def test_get_edges_for_concepts_with_data(self, db_session):
        """get_edges_for_concepts returns edges where source OR target is in concept_ids."""
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        c = await graph_service.add_concept(db_session, "C")
        await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")
        await graph_service.add_edge(db_session, b["id"], c["id"], "related")

        # Query [A, B] → both edges returned (A→B has A in set; B→C has B in set)
        edges = await graph_service.get_edges_for_concepts(db_session, [a["id"], b["id"]])
        assert len(edges) == 2
        edge_tuples = {(e["source_concept_id"], e["target_concept_id"]) for e in edges}
        assert (a["id"], b["id"]) in edge_tuples
        assert (b["id"], c["id"]) in edge_tuples

    async def test_get_edges_for_concepts_empty(self, db_session):
        """get_edges_for_concepts returns empty list when no edges exist."""
        a = await graph_service.add_concept(db_session, "A")
        edges = await graph_service.get_edges_for_concepts(db_session, [a["id"]])
        assert edges == []

    # --- Story 2.4: get_concept_by_name ---

    async def test_get_concept_by_name_found(self, db_session):
        """get_concept_by_name returns concept when found."""
        await graph_service.add_concept(db_session, "Variables", definition="Data containers")
        result = await graph_service.get_concept_by_name(db_session, "Variables")
        assert result is not None
        assert result["name"] == "Variables"
        assert result["definition"] == "Data containers"

    async def test_get_concept_by_name_not_found(self, db_session):
        """get_concept_by_name returns None when not found."""
        result = await graph_service.get_concept_by_name(db_session, "NonExistent")
        assert result is None

    # --- Story 2.4: add_edge auto_commit ---

    async def test_add_edge_auto_commit_false_no_commit(self, db_session):
        """add_edge auto_commit=False should flush but not commit; rollback discards."""
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        edge = await graph_service.add_edge(
            db_session, a["id"], b["id"], "prerequisite", auto_commit=False
        )
        assert isinstance(edge["id"], int)
        # Rollback should discard the edge
        await db_session.rollback()
        from app.repositories.graph_repo import GraphRepository
        repo = GraphRepository(db_session)
        edges = await repo.get_all_edges()
        assert len(edges) == 0

    async def test_add_edge_auto_commit_true_default(self, db_session):
        """add_edge with default auto_commit=True should commit and update in-memory graph."""
        a = await graph_service.add_concept(db_session, "A")
        b = await graph_service.add_concept(db_session, "B")
        edge = await graph_service.add_edge(db_session, a["id"], b["id"], "prerequisite")
        assert isinstance(edge["id"], int)

        # Verify in-memory graph has the edge
        G = graph_service._digraph
        assert G.has_edge(a["id"], b["id"])
