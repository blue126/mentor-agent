"""Unit tests for GraphRepository — CRUD operations on knowledge graph tables."""

from app.repositories.graph_repo import GraphRepository


class TestGraphRepository:
    """Tests using real in-memory SQLite via db_session fixture."""

    async def test_create_topic_and_get_by_name(self, db_session):
        repo = GraphRepository(db_session)
        topic_id = await repo.create_topic("Python Basics", description="Intro to Python")
        await db_session.commit()

        topic = await repo.get_topic_by_name("Python Basics")
        assert topic is not None
        assert topic["id"] == topic_id
        assert topic["name"] == "Python Basics"
        assert topic["description"] == "Intro to Python"

    async def test_create_concept_and_get_by_id(self, db_session):
        repo = GraphRepository(db_session)
        concept_id = await repo.create_concept("Decorator", definition="A function wrapper")
        await db_session.commit()

        concept = await repo.get_concept_by_id(concept_id)
        assert concept is not None
        assert concept["id"] == concept_id
        assert concept["name"] == "Decorator"
        assert concept["definition"] == "A function wrapper"

    async def test_create_concept_and_get_by_name(self, db_session):
        repo = GraphRepository(db_session)
        await repo.create_concept("Generator", definition="Yields values lazily")
        await db_session.commit()

        concept = await repo.get_concept_by_name("Generator")
        assert concept is not None
        assert concept["name"] == "Generator"
        assert concept["definition"] == "Yields values lazily"

    async def test_create_edge_and_get_by_source(self, db_session):
        repo = GraphRepository(db_session)
        c1 = await repo.create_concept("A")
        c2 = await repo.create_concept("B")
        edge_id = await repo.create_edge(c1, c2, "prerequisite")
        await db_session.commit()

        edges = await repo.get_edges_by_source(c1)
        assert len(edges) == 1
        assert edges[0]["id"] == edge_id
        assert edges[0]["source_concept_id"] == c1
        assert edges[0]["target_concept_id"] == c2
        assert edges[0]["relationship_type"] == "prerequisite"

    async def test_get_edges_by_target(self, db_session):
        repo = GraphRepository(db_session)
        c1 = await repo.create_concept("A")
        c2 = await repo.create_concept("B")
        await repo.create_edge(c1, c2, "related")
        await db_session.commit()

        edges = await repo.get_edges_by_target(c2)
        assert len(edges) == 1
        assert edges[0]["source_concept_id"] == c1
        assert edges[0]["target_concept_id"] == c2

    async def test_get_all_concepts(self, db_session):
        repo = GraphRepository(db_session)
        await repo.create_concept("X")
        await repo.create_concept("Y")
        await repo.create_concept("Z")
        await db_session.commit()

        concepts = await repo.get_all_concepts()
        assert len(concepts) == 3
        names = {c["name"] for c in concepts}
        assert names == {"X", "Y", "Z"}

    async def test_get_concepts_by_topic(self, db_session):
        repo = GraphRepository(db_session)
        topic_id = await repo.create_topic("ML")
        await repo.create_concept("Linear Regression", topic_id=topic_id)
        await repo.create_concept("Decision Tree", topic_id=topic_id)
        await repo.create_concept("Unrelated")
        await db_session.commit()

        concepts = await repo.get_concepts_by_topic(topic_id)
        assert len(concepts) == 2
        names = {c["name"] for c in concepts}
        assert names == {"Linear Regression", "Decision Tree"}

    async def test_get_all_edges(self, db_session):
        repo = GraphRepository(db_session)
        c1 = await repo.create_concept("A")
        c2 = await repo.create_concept("B")
        c3 = await repo.create_concept("C")
        await repo.create_edge(c1, c2, "prerequisite")
        await repo.create_edge(c2, c3, "related")
        await db_session.commit()

        edges = await repo.get_all_edges()
        assert len(edges) == 2

    async def test_create_topic_returns_id(self, db_session):
        repo = GraphRepository(db_session)
        id1 = await repo.create_topic("First")
        id2 = await repo.create_topic("Second")
        await db_session.commit()

        assert isinstance(id1, int)
        assert isinstance(id2, int)
        assert id1 != id2

    async def test_get_concept_by_name_not_found(self, db_session):
        repo = GraphRepository(db_session)
        result = await repo.get_concept_by_name("NonExistent")
        assert result is None
