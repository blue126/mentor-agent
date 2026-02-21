"""Graph repository — CRUD operations for knowledge graph tables."""

from datetime import datetime, timezone

from sqlalchemy import insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Concept, ConceptEdge, Topic


class GraphRepository:
    """Data access layer for topics, concepts, and concept_edges tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Topic CRUD ---

    async def create_topic(
        self,
        name: str,
        description: str | None = None,
        source_material: str | None = None,
    ) -> int:
        """Create a topic and return its id."""
        result = await self._session.execute(
            insert(Topic).values(
                name=name,
                description=description,
                source_material=source_material,
                created_at=datetime.now(timezone.utc),
            )
        )
        await self._session.flush()
        return result.inserted_primary_key[0]

    async def get_topic_by_name(self, name: str) -> dict | None:
        """Return topic dict or None."""
        result = await self._session.execute(
            select(Topic).where(Topic.name == name)
        )
        row = result.scalars().first()
        if row is None:
            return None
        return {"id": row.id, "name": row.name, "description": row.description, "source_material": row.source_material}

    async def get_all_topics(self) -> list[dict]:
        """Return all topics."""
        result = await self._session.execute(select(Topic))
        return [
            {"id": row.id, "name": row.name, "description": row.description, "source_material": row.source_material}
            for row in result.scalars().all()
        ]

    # --- Concept CRUD ---

    async def create_concept(
        self,
        name: str,
        topic_id: int | None = None,
        definition: str | None = None,
        difficulty: str | None = None,
    ) -> int:
        """Create a concept and return its id."""
        result = await self._session.execute(
            insert(Concept).values(
                name=name,
                topic_id=topic_id,
                definition=definition,
                difficulty=difficulty,
                created_at=datetime.now(timezone.utc),
            )
        )
        await self._session.flush()
        return result.inserted_primary_key[0]

    async def get_concept_by_id(self, concept_id: int) -> dict | None:
        """Return concept dict or None."""
        result = await self._session.execute(
            select(Concept).where(Concept.id == concept_id)
        )
        row = result.scalars().first()
        if row is None:
            return None
        return {
            "id": row.id,
            "name": row.name,
            "topic_id": row.topic_id,
            "definition": row.definition,
            "difficulty": row.difficulty,
        }

    async def get_concept_by_name(self, name: str) -> dict | None:
        """Return concept dict by name or None."""
        result = await self._session.execute(
            select(Concept).where(Concept.name == name)
        )
        row = result.scalars().first()
        if row is None:
            return None
        return {
            "id": row.id,
            "name": row.name,
            "topic_id": row.topic_id,
            "definition": row.definition,
            "difficulty": row.difficulty,
        }

    async def get_concepts_by_topic(self, topic_id: int) -> list[dict]:
        """Return all concepts for a given topic."""
        result = await self._session.execute(
            select(Concept).where(Concept.topic_id == topic_id)
        )
        return [
            {
                "id": row.id,
                "name": row.name,
                "topic_id": row.topic_id,
                "definition": row.definition,
                "difficulty": row.difficulty,
            }
            for row in result.scalars().all()
        ]

    async def get_all_concepts(self) -> list[dict]:
        """Return all concepts."""
        result = await self._session.execute(select(Concept))
        return [
            {
                "id": row.id,
                "name": row.name,
                "topic_id": row.topic_id,
                "definition": row.definition,
                "difficulty": row.difficulty,
            }
            for row in result.scalars().all()
        ]

    # --- Edge CRUD ---

    async def create_edge(
        self,
        source_concept_id: int,
        target_concept_id: int,
        relationship_type: str,
        weight: float = 1.0,
    ) -> int:
        """Create an edge and return its id."""
        result = await self._session.execute(
            insert(ConceptEdge).values(
                source_concept_id=source_concept_id,
                target_concept_id=target_concept_id,
                relationship_type=relationship_type,
                weight=weight,
                created_at=datetime.now(timezone.utc),
            )
        )
        await self._session.flush()
        return result.inserted_primary_key[0]

    async def get_edges_by_source(self, source_concept_id: int) -> list[dict]:
        """Return all edges originating from a given concept."""
        result = await self._session.execute(
            select(ConceptEdge).where(ConceptEdge.source_concept_id == source_concept_id)
        )
        return [
            {
                "id": row.id,
                "source_concept_id": row.source_concept_id,
                "target_concept_id": row.target_concept_id,
                "relationship_type": row.relationship_type,
                "weight": row.weight,
            }
            for row in result.scalars().all()
        ]

    async def get_edges_by_target(self, target_concept_id: int) -> list[dict]:
        """Return all edges targeting a given concept."""
        result = await self._session.execute(
            select(ConceptEdge).where(ConceptEdge.target_concept_id == target_concept_id)
        )
        return [
            {
                "id": row.id,
                "source_concept_id": row.source_concept_id,
                "target_concept_id": row.target_concept_id,
                "relationship_type": row.relationship_type,
                "weight": row.weight,
            }
            for row in result.scalars().all()
        ]

    async def get_edges_for_concepts(self, concept_ids: list[int]) -> list[dict]:
        """Return all edges where source OR target is in concept_ids."""
        if not concept_ids:
            return []
        result = await self._session.execute(
            select(ConceptEdge).where(
                or_(
                    ConceptEdge.source_concept_id.in_(concept_ids),
                    ConceptEdge.target_concept_id.in_(concept_ids),
                )
            )
        )
        return [
            {
                "id": row.id,
                "source_concept_id": row.source_concept_id,
                "target_concept_id": row.target_concept_id,
                "relationship_type": row.relationship_type,
                "weight": row.weight,
            }
            for row in result.scalars().all()
        ]

    async def get_all_edges(self) -> list[dict]:
        """Return all edges."""
        result = await self._session.execute(select(ConceptEdge))
        return [
            {
                "id": row.id,
                "source_concept_id": row.source_concept_id,
                "target_concept_id": row.target_concept_id,
                "relationship_type": row.relationship_type,
                "weight": row.weight,
            }
            for row in result.scalars().all()
        ]
