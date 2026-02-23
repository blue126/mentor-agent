"""Graph service — knowledge graph business logic with NetworkX MultiDiGraph.

Maintains a module-level in-memory MultiDiGraph that mirrors SQLite data.
All DB operations go through GraphRepository; this service adds graph
algorithms (prerequisites, related concepts, traversal).
"""

import logging
from typing import Any

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.graph_repo import GraphRepository

logger = logging.getLogger(__name__)

_VALID_RELATIONSHIP_TYPES = {"prerequisite", "related"}

# Module-level singleton — lazily loaded from DB on first access
_digraph: nx.MultiDiGraph | None = None


async def load_graph(session: AsyncSession) -> None:
    """Load all concepts and edges from DB into a fresh MultiDiGraph."""
    global _digraph  # noqa: PLW0603
    repo = GraphRepository(session)

    G = nx.MultiDiGraph()

    for concept in await repo.get_all_concepts():
        G.add_node(
            concept["id"],
            name=concept["name"],
            definition=concept["definition"],
            difficulty=concept["difficulty"],
            topic_id=concept["topic_id"],
        )

    for edge in await repo.get_all_edges():
        G.add_edge(
            edge["source_concept_id"],
            edge["target_concept_id"],
            key=edge["id"],
            relationship_type=edge["relationship_type"],
            weight=edge["weight"],
        )

    _digraph = G
    logger.info("Graph loaded: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())


async def _ensure_loaded(session: AsyncSession) -> nx.MultiDiGraph:
    """Lazily load the graph if not yet initialized.

    Note: No lock — single-user scenario; concurrent load_graph is idempotent.
    """
    if _digraph is None:
        await load_graph(session)
    return _digraph  # type: ignore[return-value]


def reset_graph() -> None:
    """Clear the in-memory graph (for testing)."""
    global _digraph  # noqa: PLW0603
    _digraph = None


async def get_topic_by_name(session: AsyncSession, name: str) -> dict[str, Any] | None:
    """Return topic dict by name, or None if not found."""
    repo = GraphRepository(session)
    return await repo.get_topic_by_name(name)


async def get_all_topics(session: AsyncSession) -> list[dict[str, Any]]:
    """Return all topics."""
    repo = GraphRepository(session)
    return await repo.get_all_topics()


async def get_concepts_by_topic(session: AsyncSession, topic_id: int) -> list[dict[str, Any]]:
    """Return all concepts for a given topic."""
    repo = GraphRepository(session)
    return await repo.get_concepts_by_topic(topic_id)


async def get_concept_by_name(session: AsyncSession, name: str) -> dict[str, Any] | None:
    """Return concept dict by name, or None if not found."""
    repo = GraphRepository(session)
    return await repo.get_concept_by_name(name)


async def get_edges_for_concepts(session: AsyncSession, concept_ids: list[int]) -> list[dict[str, Any]]:
    """Return all edges where source or target is in concept_ids."""
    repo = GraphRepository(session)
    return await repo.get_edges_for_concepts(concept_ids)


async def delete_topic_cascade(
    session: AsyncSession,
    topic_id: int,
    *,
    auto_commit: bool = True,
) -> None:
    """Delete topic and all its concepts + edges via cascade.

    When auto_commit=False, caller must commit/rollback.
    """
    repo = GraphRepository(session)
    await repo.delete_topic_cascade(topic_id)
    if auto_commit:
        await session.commit()
        # Rebuild in-memory graph after deletion
        await load_graph(session)


async def add_topic(
    session: AsyncSession,
    name: str,
    description: str | None = None,
    source_material: str | None = None,
    *,
    auto_commit: bool = True,
) -> dict[str, Any]:
    """Create a topic. Returns {id, name}.

    When auto_commit=False, only flushes to get the ID; caller must commit/rollback.
    """
    repo = GraphRepository(session)
    topic_id = await repo.create_topic(name, description, source_material)
    if auto_commit:
        await session.commit()
    return {"id": topic_id, "name": name}


async def add_concept(
    session: AsyncSession,
    name: str,
    topic_id: int | None = None,
    definition: str | None = None,
    difficulty: str | None = None,
    *,
    auto_commit: bool = True,
) -> dict[str, Any]:
    """Create a concept, write to DB and add to in-memory MultiDiGraph. Returns {id, name}.

    When auto_commit=False, only flushes to get the ID without commit or graph update.
    Caller must commit and call load_graph() to rebuild the in-memory graph.
    """
    repo = GraphRepository(session)
    concept_id = await repo.create_concept(name, topic_id, definition, difficulty)

    if auto_commit:
        await session.commit()
        # Update in-memory graph (commit succeeded, safe to update memory)
        try:
            G = await _ensure_loaded(session)
            G.add_node(
                concept_id,
                name=name,
                definition=definition,
                difficulty=difficulty,
                topic_id=topic_id,
            )
        except Exception:
            logger.exception("Failed to update in-memory graph after add_concept; rebuilding")
            try:
                await load_graph(session)
            except Exception:
                logger.exception("Graph rebuild also failed; will retry on next access")
                reset_graph()

    return {"id": concept_id, "name": name}


async def add_edge(
    session: AsyncSession,
    source_concept_id: int,
    target_concept_id: int,
    relationship_type: str,
    weight: float = 1.0,
    *,
    auto_commit: bool = True,
) -> dict[str, Any]:
    """Create an edge, write to DB and add to in-memory MultiDiGraph.

    Validates relationship_type and concept existence before writing.
    Returns {id, source_concept_id, target_concept_id, relationship_type}.

    When auto_commit=False, only flushes to get the ID without commit or graph update.
    Caller must commit and call load_graph() to rebuild the in-memory graph.
    """
    # Input validation
    if relationship_type not in _VALID_RELATIONSHIP_TYPES:
        raise ValueError(
            f"Invalid relationship_type '{relationship_type}'. Must be one of: {_VALID_RELATIONSHIP_TYPES}"
        )

    repo = GraphRepository(session)

    # Verify both concepts exist
    source = await repo.get_concept_by_id(source_concept_id)
    if source is None:
        raise ValueError(f"Source concept {source_concept_id} does not exist")
    target = await repo.get_concept_by_id(target_concept_id)
    if target is None:
        raise ValueError(f"Target concept {target_concept_id} does not exist")

    edge_id = await repo.create_edge(source_concept_id, target_concept_id, relationship_type, weight)

    if auto_commit:
        await session.commit()

        # Update in-memory graph
        try:
            G = await _ensure_loaded(session)
            G.add_edge(
                source_concept_id,
                target_concept_id,
                key=edge_id,
                relationship_type=relationship_type,
                weight=weight,
            )
        except Exception:
            logger.exception("Failed to update in-memory graph after add_edge; rebuilding")
            try:
                await load_graph(session)
            except Exception:
                logger.exception("Graph rebuild also failed; will retry on next access")
                reset_graph()
    # else: repo.create_edge already flushed; caller manages commit/rollback

    return {
        "id": edge_id,
        "source_concept_id": source_concept_id,
        "target_concept_id": target_concept_id,
        "relationship_type": relationship_type,
    }


async def get_prerequisites(session: AsyncSession, concept_id: int) -> list[dict[str, Any]]:
    """Return prerequisite concepts for a given concept.

    Edge direction: source→target means "source depends on target".
    get_prerequisites(A) returns targets of A's outgoing prerequisite edges.
    """
    G = await _ensure_loaded(session)

    if concept_id not in G:
        return []

    prerequisites = []
    for _, target, data in G.out_edges(concept_id, data=True):
        if data.get("relationship_type") == "prerequisite":
            node_data = G.nodes[target]
            prerequisites.append({"id": target, **node_data})

    return prerequisites


async def get_related_concepts(session: AsyncSession, concept_id: int) -> list[dict[str, Any]]:
    """Return related concepts (bidirectional) for a given concept.

    Searches both outgoing and incoming edges with type="related".
    """
    G = await _ensure_loaded(session)

    if concept_id not in G:
        return []

    related: dict[int, dict[str, Any]] = {}

    # Outgoing related edges
    for _, target, data in G.out_edges(concept_id, data=True):
        if data.get("relationship_type") == "related":
            related[target] = {"id": target, **G.nodes[target]}

    # Incoming related edges
    for source, _, data in G.in_edges(concept_id, data=True):
        if data.get("relationship_type") == "related":
            related[source] = {"id": source, **G.nodes[source]}

    return list(related.values())


async def get_concept_graph_summary(session: AsyncSession) -> str:
    """Return a summary string of the graph (node count, edge count, topics)."""
    G = await _ensure_loaded(session)
    repo = GraphRepository(session)

    topics = await repo.get_all_topics()
    topic_names = [t["name"] for t in topics]

    return (
        f"Knowledge graph: {G.number_of_nodes()} concepts, "
        f"{G.number_of_edges()} edges, "
        f"{len(topic_names)} topics ({', '.join(topic_names) if topic_names else 'none'})"
    )
