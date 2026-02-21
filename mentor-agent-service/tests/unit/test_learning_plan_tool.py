"""Unit tests for learning_plan_tool — generate and get learning plans."""

import json
from unittest.mock import AsyncMock, patch

from app.tools.learning_plan_tool import (
    _format_plan,
    _format_plan_from_db,
    _is_section_name,
    _parse_and_validate_plan,
    generate_learning_plan,
    get_learning_plan,
)

_VALID_JSON = json.dumps([
    {"chapter": "1. Introduction", "sections": ["1.1 Getting Started", "1.2 Basic Concepts"]},
    {"chapter": "2. Core Topics", "sections": ["2.1 Topic A", "2.2 Topic B"]},
])

_VALID_JSON_FENCED = f"```json\n{_VALID_JSON}\n```"


# --- _parse_and_validate_plan tests ---


class TestParseAndValidatePlan:
    def test_valid_json(self):
        result = _parse_and_validate_plan(_VALID_JSON)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["chapter"] == "1. Introduction"
        assert result[0]["sections"] == ["1.1 Getting Started", "1.2 Basic Concepts"]

    def test_valid_json_fenced(self):
        result = _parse_and_validate_plan(_VALID_JSON_FENCED)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_invalid_json(self):
        result = _parse_and_validate_plan("not json at all")
        assert isinstance(result, str)
        assert "Error: Parse" in result

    def test_not_array(self):
        result = _parse_and_validate_plan('{"chapter": "foo"}')
        assert isinstance(result, str)
        assert "Expected JSON array" in result

    def test_empty_array(self):
        result = _parse_and_validate_plan("[]")
        assert isinstance(result, str)
        assert "No chapters found" in result

    def test_too_many_chapters(self):
        data = [{"chapter": f"Ch{i}", "sections": ["s1"]} for i in range(51)]
        result = _parse_and_validate_plan(json.dumps(data))
        assert isinstance(result, str)
        assert "Too many chapters" in result

    def test_too_many_sections(self):
        data = [{"chapter": "Ch1", "sections": [f"s{i}" for i in range(31)]}]
        result = _parse_and_validate_plan(json.dumps(data))
        assert isinstance(result, str)
        assert "too many sections" in result

    def test_missing_chapter_field(self):
        data = [{"sections": ["s1"]}]
        result = _parse_and_validate_plan(json.dumps(data))
        assert isinstance(result, str)
        assert "missing or empty" in result

    def test_chapter_name_too_long(self):
        data = [{"chapter": "x" * 201, "sections": ["s1"]}]
        result = _parse_and_validate_plan(json.dumps(data))
        assert isinstance(result, str)
        assert "too long" in result

    def test_section_name_too_long(self):
        data = [{"chapter": "Ch1", "sections": ["x" * 201]}]
        result = _parse_and_validate_plan(json.dumps(data))
        assert isinstance(result, str)
        assert "too long" in result

    def test_deduplicates_sections(self):
        data = [{"chapter": "Ch1", "sections": ["s1", "S1", "s2"]}]
        result = _parse_and_validate_plan(json.dumps(data))
        assert isinstance(result, list)
        assert len(result[0]["sections"]) == 2


# --- _is_section_name tests ---


class TestIsSectionName:
    def test_numbered_section(self):
        assert _is_section_name("1.1 Getting Started") is True

    def test_deep_numbered_section(self):
        assert _is_section_name("2.3.1 Advanced Topic") is True

    def test_chapter_number_no_dot(self):
        """A plain chapter number like '1 Intro' is NOT a section."""
        assert _is_section_name("1 Introduction") is False

    def test_chapter_with_trailing_dot(self):
        """'1. Introduction' — single number with trailing dot, no sub-dot."""
        assert _is_section_name("1. Introduction") is False

    def test_unnumbered_name(self):
        assert _is_section_name("Introduction") is False

    def test_empty_string(self):
        assert _is_section_name("") is False

    def test_letter_prefix_with_dot(self):
        """'A.1 Topic' — starts with letter, not digit."""
        assert _is_section_name("A.1 Topic") is False


# --- _format_plan_from_db tests ---


class TestFormatPlanFromDb:
    def test_standard_chapters_and_sections(self):
        """Normal case: chapters (no sub-dot) followed by sections (sub-dot)."""
        concepts = [
            {"name": "1 Variables"},
            {"name": "1.1 Types"},
            {"name": "1.2 Assignment"},
            {"name": "2 Control Flow"},
            {"name": "2.1 If Statements"},
        ]
        result = _format_plan_from_db("Python", concepts)
        assert "Variables" in result
        assert "Types" in result
        assert "Control Flow" in result

    def test_orphan_sections_before_first_chapter(self):
        """Sections appearing before any chapter are attached to the first chapter found."""
        concepts = [
            {"name": "1.1 Orphan Section"},
            {"name": "1.2 Another Orphan"},
            {"name": "1 First Chapter"},
            {"name": "1.3 Normal Section"},
        ]
        result = _format_plan_from_db("Book", concepts)
        # All content should appear — orphans attached to "1 First Chapter"
        assert "Orphan Section" in result
        assert "First Chapter" in result
        assert "Normal Section" in result

    def test_all_sections_no_chapters(self):
        """All concepts look like sections — each treated as a chapter."""
        concepts = [
            {"name": "1.1 Topic A"},
            {"name": "1.2 Topic B"},
        ]
        result = _format_plan_from_db("Book", concepts)
        assert "Topic A" in result
        assert "Topic B" in result

    def test_unnumbered_names_treated_as_chapters(self):
        """Names without numbers are treated as chapters."""
        concepts = [
            {"name": "Introduction"},
            {"name": "1.1 Getting Started"},
            {"name": "Advanced Topics"},
        ]
        result = _format_plan_from_db("Book", concepts)
        assert "Introduction" in result
        assert "Advanced Topics" in result


# --- _format_plan tests ---


class TestFormatPlan:
    def test_format_plan_output(self):
        chapters = [
            {"chapter": "Introduction", "sections": ["Getting Started", "Basics"]},
            {"chapter": "Advanced", "sections": ["Deep Dive"]},
        ]
        result = _format_plan("My Book", chapters)
        assert "My Book" in result
        assert "Chapter 1: Introduction" in result
        assert "Chapter 2: Advanced" in result
        assert "2 chapters, 3 sections" in result
        assert "Plan created" in result


# --- generate_learning_plan tests ---


class TestGenerateLearningPlan:
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_success_path(self, mock_rag, mock_llm, mock_gs, mock_sf):
        """Successful generate: RAG + LLM → graph_service calls → formatted output."""
        # Mock session
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        # No existing topic
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        # RAG returns content
        mock_rag.return_value = "Chapter 1: Intro\n1.1 Start\nChapter 2: Core\n2.1 Deep"

        # LLM returns valid JSON
        mock_llm.return_value = _VALID_JSON

        # Graph service write operations
        mock_gs.add_topic = AsyncMock(return_value={"id": 1, "name": "Test Book"})
        mock_gs.add_concept = AsyncMock(return_value={"id": 1, "name": "concept"})
        mock_gs.load_graph = AsyncMock()

        result = await generate_learning_plan("Test Book")

        assert "Learning Plan: Test Book" in result
        assert "Chapter 1" in result
        assert "Chapter 2" in result
        mock_gs.add_topic.assert_called_once()
        assert mock_gs.add_concept.call_count == 6  # 2 chapters + 4 sections

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_rag_failure(self, mock_rag, mock_gs, mock_sf):
        """RAG failure → returns error string with hint."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        mock_rag.return_value = "Error: Open WebUI is unreachable"

        result = await generate_learning_plan("Test Book")

        assert "Error" in result
        assert "Could not retrieve document content" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_rag_no_relevant_content(self, mock_rag, mock_gs, mock_sf):
        """RAG returns 'No relevant content' → treated as failure with hint."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        mock_rag.return_value = "No relevant content found for query."

        result = await generate_learning_plan("Test Book")

        assert "Error" in result
        assert "Could not retrieve document content" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_llm_failure(self, mock_rag, mock_llm, mock_gs, mock_sf):
        """LLM failure → returns error string."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_rag.return_value = "Some book content here..."

        mock_llm.return_value = "Error: LLM service unavailable"

        result = await generate_learning_plan("Test Book")

        assert "Error" in result
        assert "Failed to analyze document structure" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_json_validation_failure(self, mock_rag, mock_llm, mock_gs, mock_sf):
        """JSON validation failure → returns parse error."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_rag.return_value = "Some content"

        mock_llm.return_value = "not valid json"

        result = await generate_learning_plan("Test Book")

        assert "Error" in result
        assert "Could not parse" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_json_validation_error_passthrough(self, mock_rag, mock_llm, mock_gs, mock_sf):
        """Validation error → returns detail from _parse_and_validate_plan."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_rag.return_value = "Some content"

        # Valid JSON but too many chapters → triggers Validation error
        data = [{"chapter": f"Ch{i}", "sections": ["s1"]} for i in range(51)]
        mock_llm.return_value = json.dumps(data)

        result = await generate_learning_plan("Test Book")

        assert "Extracted structure is invalid" in result
        assert "Too many chapters" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_llm_timeout(self, mock_rag, mock_llm, mock_gs, mock_sf):
        """LLM call exceeding timeout → returns timeout error."""
        import asyncio

        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_rag.return_value = "Some content"

        async def slow_llm(*args, **kwargs):
            await asyncio.sleep(60)

        mock_llm.side_effect = slow_llm

        # Patch timeout to 0.01s so the test doesn't actually wait 30s
        with patch("app.tools.learning_plan_tool._LLM_TIMEOUT_SECONDS", 0.01):
            result = await generate_learning_plan("Test Book")

        assert "Error" in result
        assert "timed out" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_idempotent_existing_topic(self, mock_gs, mock_sf):
        """Existing topic → returns existing plan instead of creating duplicate."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(return_value={"id": 1, "name": "Test Book"})
        mock_gs.get_concepts_by_topic = AsyncMock(
            return_value=[
                {"id": 1, "name": "1. Intro", "topic_id": 1, "definition": None, "difficulty": None},
                {"id": 2, "name": "1.1 Start", "topic_id": 1, "definition": None, "difficulty": None},
            ]
        )

        result = await generate_learning_plan("Test Book")

        assert "already exists" in result
        mock_gs.add_topic.assert_not_called()

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_atomic_rollback_on_db_error(self, mock_rag, mock_llm, mock_gs, mock_sf):
        """DB error during write → rollback, no dirty data."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        # First session call: idempotency check (no existing)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        mock_rag.return_value = "Content"
        mock_llm.return_value = _VALID_JSON

        # add_topic succeeds but add_concept fails on 2nd call
        mock_gs.add_topic = AsyncMock(return_value={"id": 1, "name": "Test Book"})
        call_count = 0

        async def mock_add_concept(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise Exception("DB write failed")
            return {"id": call_count, "name": "concept"}

        mock_gs.add_concept = mock_add_concept

        result = await generate_learning_plan("Test Book")

        assert "Error" in result
        assert "Failed to save learning plan" in result
        mock_session.rollback.assert_called_once()

    async def test_empty_source_name(self):
        result = await generate_learning_plan("   ")
        assert "Error" in result
        assert "source_name is empty" in result


# --- get_learning_plan tests ---


class TestGetLearningPlan:
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_with_data(self, mock_gs, mock_sf):
        """Has data → returns formatted plan."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(
            return_value={"id": 1, "name": "Python Book", "description": None, "source_material": None}
        )
        mock_gs.get_concepts_by_topic = AsyncMock(
            return_value=[
                {"id": 1, "name": "1 Introduction", "topic_id": 1, "definition": None, "difficulty": None},
                {"id": 2, "name": "1.1 Getting Started", "topic_id": 1, "definition": None, "difficulty": None},
                {"id": 3, "name": "2 Advanced", "topic_id": 1, "definition": None, "difficulty": None},
            ]
        )

        result = await get_learning_plan(topic_name="Python Book")
        assert "Python Book" in result
        assert "Introduction" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_no_data(self, mock_gs, mock_sf):
        """No plans → returns friendly hint."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_all_topics = AsyncMock(return_value=[])

        result = await get_learning_plan()
        assert "No learning plans found" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_specific_topic_not_found(self, mock_gs, mock_sf):
        """Named topic not found → returns friendly hint."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        result = await get_learning_plan(topic_name="NonExistent")
        assert "No learning plan found" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_list_all_topics(self, mock_gs, mock_sf):
        """No topic_name → list all plans with concept counts."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_all_topics = AsyncMock(
            return_value=[
                {"id": 1, "name": "Book A", "description": None, "source_material": None},
                {"id": 2, "name": "Book B", "description": None, "source_material": None},
            ]
        )
        mock_gs.get_concepts_by_topic = AsyncMock(
            side_effect=[
                [{"id": 1, "name": "c1"}, {"id": 2, "name": "c2"}],
                [{"id": 3, "name": "c3"}],
            ]
        )

        result = await get_learning_plan()
        assert "Book A" in result
        assert "Book B" in result
        assert "2 plans" in result
