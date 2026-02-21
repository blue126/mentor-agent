"""Unit tests for extract_relationships_tool — mock LLM + graph_service."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.extract_relationships_tool import (
    _format_relationships_output,
    _parse_and_validate_relationships,
    extract_concept_relationships,
)


# --- Helper fixtures and constants ---

_TOPIC = {"id": 1, "name": "Python Basics", "description": None, "source_material": None}
_CONCEPTS = [
    {"id": 10, "name": "Variables", "topic_id": 1, "definition": "Data containers", "difficulty": None},
    {"id": 11, "name": "Data Types", "topic_id": 1, "definition": "Types of data", "difficulty": None},
    {"id": 12, "name": "Functions", "topic_id": 1, "definition": "Reusable code blocks", "difficulty": None},
    {"id": 13, "name": "OOP", "topic_id": 1, "definition": "Object-Oriented Programming", "difficulty": None},
]
_NAME_TO_ID = {c["name"].strip().lower(): c["id"] for c in _CONCEPTS}

_VALID_LLM_JSON = json.dumps([
    {"source": "Functions", "target": "Variables", "type": "prerequisite"},
    {"source": "OOP", "target": "Functions", "type": "prerequisite"},
    {"source": "Variables", "target": "Data Types", "type": "related"},
])


class _FakeSessionContext:
    """Sync-callable that returns an async context manager wrapping a mock session."""

    def __init__(self, session=None):
        self._session = session or AsyncMock()

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


# --- Tests for _parse_and_validate_relationships ---


class TestParseAndValidateRelationships:
    def test_valid_json(self):
        result = _parse_and_validate_relationships(_VALID_LLM_JSON, _NAME_TO_ID)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_json_with_code_fences(self):
        wrapped = f"```json\n{_VALID_LLM_JSON}\n```"
        result = _parse_and_validate_relationships(wrapped, _NAME_TO_ID)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_invalid_json(self):
        result = _parse_and_validate_relationships("not valid json", _NAME_TO_ID)
        assert isinstance(result, str)
        assert "Error: Parse" in result

    def test_not_an_array(self):
        result = _parse_and_validate_relationships('{"source": "A"}', _NAME_TO_ID)
        assert isinstance(result, str)
        assert "Expected JSON array" in result

    def test_empty_array(self):
        result = _parse_and_validate_relationships("[]", _NAME_TO_ID)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_too_many_relationships(self):
        data = [{"source": "Variables", "target": "Data Types", "type": "related"}] * 201
        result = _parse_and_validate_relationships(json.dumps(data), _NAME_TO_ID)
        assert isinstance(result, str)
        assert "Too many relationships" in result

    def test_invalid_relationship_type_all_filtered(self):
        """All items have invalid types → returns Validation error string."""
        data = [{"source": "Variables", "target": "Data Types", "type": "unknown"}]
        result = _parse_and_validate_relationships(json.dumps(data), _NAME_TO_ID)
        assert isinstance(result, str)
        assert "Error: Validation" in result

    def test_invalid_relationship_type_partial(self):
        """Mix of valid and invalid types → valid items kept, invalid skipped."""
        data = [
            {"source": "Variables", "target": "Data Types", "type": "unknown"},
            {"source": "Functions", "target": "Variables", "type": "prerequisite"},
        ]
        result = _parse_and_validate_relationships(json.dumps(data), _NAME_TO_ID)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "prerequisite"

    def test_unknown_concept_name(self):
        data = [{"source": "Variables", "target": "NonExistent", "type": "related"}]
        result = _parse_and_validate_relationships(json.dumps(data), _NAME_TO_ID)
        assert isinstance(result, list)
        assert len(result) == 0  # Skipped

    def test_self_referencing_edge(self):
        data = [{"source": "Variables", "target": "Variables", "type": "related"}]
        result = _parse_and_validate_relationships(json.dumps(data), _NAME_TO_ID)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_duplicate_edges_deduplicated(self):
        data = [
            {"source": "Variables", "target": "Data Types", "type": "related"},
            {"source": "Variables", "target": "Data Types", "type": "related"},
        ]
        result = _parse_and_validate_relationships(json.dumps(data), _NAME_TO_ID)
        assert isinstance(result, list)
        assert len(result) == 1


# --- Tests for extract_concept_relationships ---


class TestExtractConceptRelationships:

    @patch("app.tools.extract_relationships_tool.get_chat_completion")
    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_success_path(self, mock_factory, mock_gs, mock_llm):
        """Happy path: topic exists, concepts exist, LLM returns valid JSON."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=_CONCEPTS)
        mock_gs.get_edges_for_concepts = AsyncMock(return_value=[])
        mock_gs.add_edge = AsyncMock(return_value={"id": 1, "source_concept_id": 10, "target_concept_id": 11, "relationship_type": "prerequisite"})
        mock_gs.load_graph = AsyncMock()
        mock_llm.return_value = _VALID_LLM_JSON

        result = await extract_concept_relationships("Python Basics")

        assert "Concept Relationships: Python Basics" in result
        assert "prerequisite" in result.lower() or "Prerequisites" in result
        assert "Related" in result
        assert mock_gs.add_edge.call_count == 3
        mock_gs.load_graph.assert_awaited_once()

    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_topic_not_found(self, mock_factory, mock_gs):
        """Topic doesn't exist → returns error string."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)

        result = await extract_concept_relationships("NonExistent")

        assert "Error: Topic 'NonExistent' not found" in result
        assert "generate_learning_plan" in result

    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_topic_has_fewer_than_2_concepts(self, mock_factory, mock_gs):
        """Topic with <2 concepts → returns error string."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=[_CONCEPTS[0]])

        result = await extract_concept_relationships("Python Basics")

        assert "fewer than 2 concepts" in result

    @patch("app.tools.extract_relationships_tool.get_chat_completion")
    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_llm_failure(self, mock_factory, mock_gs, mock_llm):
        """LLM returns error string → fail soft."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=_CONCEPTS)
        mock_llm.return_value = "Error: LLM service unavailable"

        result = await extract_concept_relationships("Python Basics")

        assert "Error: Failed to analyze concept relationships" in result

    @patch("app.tools.extract_relationships_tool.get_chat_completion")
    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_llm_timeout(self, mock_factory, mock_gs, mock_llm):
        """LLM times out → fail soft with timeout error."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=_CONCEPTS)

        async def slow_llm(*args, **kwargs):
            await asyncio.sleep(100)

        mock_llm.side_effect = slow_llm

        # Temporarily reduce timeout for test speed
        with patch("app.tools.extract_relationships_tool._LLM_TIMEOUT_SECONDS", 0.01):
            result = await extract_concept_relationships("Python Basics")

        assert "Error: LLM analysis timed out" in result

    @patch("app.tools.extract_relationships_tool.get_chat_completion")
    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_json_parse_failure(self, mock_factory, mock_gs, mock_llm):
        """LLM returns invalid JSON → Parse error (fail soft)."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=_CONCEPTS)
        mock_llm.return_value = "This is not JSON at all"

        result = await extract_concept_relationships("Python Basics")

        assert "Error: Could not parse" in result

    @patch("app.tools.extract_relationships_tool.get_chat_completion")
    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_json_validation_failure(self, mock_factory, mock_gs, mock_llm):
        """LLM returns JSON with all invalid relationship types → Validation error (fail soft)."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=_CONCEPTS)
        mock_llm.return_value = json.dumps([
            {"source": "Variables", "target": "Data Types", "type": "invalid_type"},
        ])

        result = await extract_concept_relationships("Python Basics")

        assert "Error: Extracted relationships are invalid" in result

    @patch("app.tools.extract_relationships_tool.get_chat_completion")
    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_unknown_concept_in_llm_response(self, mock_factory, mock_gs, mock_llm):
        """LLM references concepts not in the graph → skipped with warning."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=_CONCEPTS)
        mock_gs.get_edges_for_concepts = AsyncMock(return_value=[])
        mock_gs.add_edge = AsyncMock(return_value={"id": 1, "source_concept_id": 10, "target_concept_id": 11, "relationship_type": "related"})
        mock_gs.load_graph = AsyncMock()

        # One valid, one with unknown concept
        llm_output = json.dumps([
            {"source": "Variables", "target": "Data Types", "type": "related"},
            {"source": "Variables", "target": "UnknownConcept", "type": "prerequisite"},
        ])
        mock_llm.return_value = llm_output

        result = await extract_concept_relationships("Python Basics")

        assert "Concept Relationships" in result
        assert mock_gs.add_edge.call_count == 1  # Only one valid edge

    @patch("app.tools.extract_relationships_tool.get_chat_completion")
    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_idempotent_skips_existing_edges(self, mock_factory, mock_gs, mock_llm):
        """Existing edges are skipped, return summary shows skipped count."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=_CONCEPTS)
        # One existing edge matches LLM output
        mock_gs.get_edges_for_concepts = AsyncMock(return_value=[
            {"id": 99, "source_concept_id": 12, "target_concept_id": 10, "relationship_type": "prerequisite", "weight": 1.0},
        ])
        mock_gs.add_edge = AsyncMock(return_value={"id": 1, "source_concept_id": 10, "target_concept_id": 11, "relationship_type": "prerequisite"})
        mock_gs.load_graph = AsyncMock()
        mock_llm.return_value = _VALID_LLM_JSON

        result = await extract_concept_relationships("Python Basics")

        assert "Skipped (existing): 1" in result
        assert "New: 2" in result
        assert mock_gs.add_edge.call_count == 2  # 3 total - 1 existing = 2 new

    @patch("app.tools.extract_relationships_tool.get_chat_completion")
    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_db_write_failure_rollback(self, mock_factory, mock_gs, mock_llm):
        """DB write failure → rollback + fail soft error."""
        mock_session = AsyncMock()
        mock_factory.return_value = _FakeSessionContext(mock_session)
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=_CONCEPTS)
        mock_gs.get_edges_for_concepts = AsyncMock(return_value=[])
        mock_gs.add_edge = AsyncMock(side_effect=Exception("DB write error"))
        mock_llm.return_value = _VALID_LLM_JSON

        result = await extract_concept_relationships("Python Basics")

        assert "Error: Failed to save relationships to database" in result
        mock_session.rollback.assert_awaited_once()

    @patch("app.tools.extract_relationships_tool.get_chat_completion")
    @patch("app.tools.extract_relationships_tool.graph_service")
    @patch("app.tools.extract_relationships_tool.async_session_factory")
    async def test_empty_relationships_from_llm(self, mock_factory, mock_gs, mock_llm):
        """LLM returns empty array → no meaningful relationships message."""
        mock_factory.return_value = _FakeSessionContext()
        mock_gs.get_topic_by_name = AsyncMock(return_value=_TOPIC)
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=_CONCEPTS)
        mock_llm.return_value = "[]"

        result = await extract_concept_relationships("Python Basics")

        assert "No meaningful relationships identified" in result


# --- Tests for _format_relationships_output ---


class TestFormatRelationshipsOutput:
    def test_format_output(self):
        rels = [
            {"source_id": 12, "target_id": 10, "type": "prerequisite", "source_name": "Functions", "target_name": "Variables"},
            {"source_id": 10, "target_id": 11, "type": "related", "source_name": "Variables", "target_name": "Data Types"},
        ]
        result = _format_relationships_output("Python Basics", rels, created_count=2, skipped_count=0)

        assert "Python Basics" in result
        assert "Functions" in result
        assert "Variables" in result
        assert "1 prerequisite edges" in result
        assert "1 related edges" in result
        assert "New: 2" in result
        assert "Skipped (existing): 0" in result
