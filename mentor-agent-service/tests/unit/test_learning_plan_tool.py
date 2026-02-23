"""Unit tests for learning_plan_tool — generate and get learning plans."""

import json
from unittest.mock import AsyncMock, patch

from app.tools.learning_plan_tool import (
    _clean_filename,
    _filter_chunks_by_source,
    _format_ambiguous_matches,
    _format_plan,
    _format_plan_from_db,
    _is_section_name,
    _match_filename,
    _parse_and_validate_plan,
    _stem,
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


# --- Helper function tests ---


class TestCleanFilename:
    def test_removes_extension(self):
        assert _clean_filename("Pro Git.pdf") == "Pro Git"

    def test_no_extension(self):
        assert _clean_filename("Pro Git") == "Pro Git"

    def test_multiple_dots(self):
        assert _clean_filename("file.name.pdf") == "file.name"

    def test_strips_whitespace(self):
        assert _clean_filename("  Pro Git.pdf  ") == "Pro Git"


class TestMatchFilename:
    def test_exact_match(self):
        filenames = ["Pro Git.pdf", "The Pragmatic Programmer.pdf"]
        assert _match_filename("Pro Git.pdf", filenames) == "Pro Git.pdf"

    def test_without_extension(self):
        filenames = ["Pro Git.pdf", "The Pragmatic Programmer.pdf"]
        assert _match_filename("Pro Git", filenames) == "Pro Git.pdf"

    def test_substring_unique(self):
        filenames = ["Pro Git.pdf", "The Pragmatic Programmer.pdf"]
        assert _match_filename("Pragmatic", filenames) == "The Pragmatic Programmer.pdf"

    def test_substring_ambiguous(self):
        filenames = ["Pro Git.pdf", "Git in Practice.pdf"]
        result = _match_filename("git", filenames)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_no_match(self):
        filenames = ["Pro Git.pdf", "The Pragmatic Programmer.pdf"]
        assert _match_filename("Django", filenames) is None

    def test_case_insensitive(self):
        filenames = ["Pro Git.pdf"]
        assert _match_filename("pro git", filenames) == "Pro Git.pdf"


class TestStem:
    def test_with_extension(self):
        assert _stem("Pro Git.pdf") == "pro git"

    def test_without_extension(self):
        assert _stem("Pro Git") == "pro git"

    def test_multiple_dots(self):
        assert _stem("file.name.pdf") == "file.name"

    def test_whitespace(self):
        assert _stem("  Pro Git.pdf  ") == "pro git"


class TestFilterChunksBySource:
    def test_filters_by_name(self):
        docs = ["chunk1", "chunk2", "chunk3"]
        metas = [
            {"name": "Pro Git.pdf", "source": ""},
            {"name": "Other Book.pdf", "source": ""},
            {"name": "Pro Git.pdf", "source": ""},
        ]
        dists = [0.1, 0.2, 0.3]
        f_docs, f_metas, f_dists = _filter_chunks_by_source(docs, metas, dists, "Pro Git.pdf")
        assert len(f_docs) == 2
        assert f_docs == ["chunk1", "chunk3"]
        assert f_dists == [0.1, 0.3]

    def test_filters_by_source_field(self):
        docs = ["chunk1", "chunk2"]
        metas = [
            {"name": "", "source": "/path/to/Pro Git.pdf"},
            {"name": "", "source": "/path/to/Other.pdf"},
        ]
        dists = [0.1, 0.2]
        f_docs, f_metas, f_dists = _filter_chunks_by_source(docs, metas, dists, "Pro Git.pdf")
        assert len(f_docs) == 1

    def test_case_insensitive(self):
        docs = ["chunk1"]
        metas = [{"name": "PRO GIT.PDF", "source": ""}]
        dists = [0.1]
        f_docs, _, _ = _filter_chunks_by_source(docs, metas, dists, "pro git.pdf")
        assert len(f_docs) == 1

    def test_empty_metadata(self):
        docs = ["chunk1"]
        metas = [{}]
        dists = [0.1]
        f_docs, _, _ = _filter_chunks_by_source(docs, metas, dists, "file.pdf")
        assert len(f_docs) == 0

    def test_metadata_name_without_extension(self):
        """Root cause: metadata name has no .pdf but target does -> should still match."""
        docs = ["chunk1", "chunk2"]
        metas = [
            {"name": "Test-Driven Development By Example"},
            {"name": "Other Book"},
        ]
        dists = [0.1, 0.2]
        f_docs, _, _ = _filter_chunks_by_source(
            docs, metas, dists, "Test-Driven Development By Example.pdf"
        )
        assert len(f_docs) == 1
        assert f_docs == ["chunk1"]

    def test_target_without_extension_matches_metadata_with(self):
        """Target has no extension but metadata does -> should match via stem."""
        docs = ["chunk1"]
        metas = [{"name": "Pro Git.pdf"}]
        dists = [0.1]
        f_docs, _, _ = _filter_chunks_by_source(docs, metas, dists, "Pro Git")
        assert len(f_docs) == 1

    def test_partial_name_in_longer_metadata(self):
        """Metadata name is a substring of target stem -> bidirectional match."""
        docs = ["chunk1"]
        metas = [{"name": "TDD By Example"}]
        dists = [0.1]
        # "tdd by example" is in target stem? No. But target stem "test-driven..." is not in "tdd by example"
        # This should NOT match — different titles
        f_docs, _, _ = _filter_chunks_by_source(
            docs, metas, dists, "Test-Driven Development By Example.pdf"
        )
        assert len(f_docs) == 0

    def test_source_path_match(self):
        """Target stem found in source path."""
        docs = ["chunk1"]
        metas = [{"name": "", "source": "/uploads/Test-Driven Development By Example/chunk_0.txt"}]
        dists = [0.1]
        f_docs, _, _ = _filter_chunks_by_source(
            docs, metas, dists, "Test-Driven Development By Example.pdf"
        )
        assert len(f_docs) == 1


class TestFormatAmbiguousMatches:
    def test_format(self):
        result = _format_ambiguous_matches("git", ["Pro Git.pdf", "Git in Practice.pdf"])
        assert "Multiple documents match" in result
        assert "Pro Git.pdf" in result
        assert "Git in Practice.pdf" in result
        assert "exact filename" in result


# --- generate_learning_plan tests ---


class TestGenerateLearningPlan:
    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_success_path(self, mock_rag, mock_llm, mock_gs, mock_sf, _mock_resolve, mock_files):
        """Successful generate: RAG + LLM -> graph_service calls -> formatted output."""
        # Mock session
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        # No existing topic
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        # Single file in collection
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        # RAG returns content
        mock_rag.return_value = "Chapter 1: Intro\n1.1 Start\nChapter 2: Core\n2.1 Deep"

        # LLM returns valid JSON
        mock_llm.return_value = _VALID_JSON

        # Graph service write operations
        mock_gs.add_topic = AsyncMock(return_value={"id": 1, "name": "Test Book"})
        mock_gs.add_concept = AsyncMock(return_value={"id": 1, "name": "concept"})
        mock_gs.load_graph = AsyncMock()

        result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "Learning Plan: Test Book" in result
        assert "Chapter 1" in result
        assert "Chapter 2" in result
        mock_gs.add_topic.assert_called_once()
        # Verify description contains valid JSON plan structure
        call_kwargs = mock_gs.add_topic.call_args
        desc = call_kwargs.kwargs.get("description") or call_kwargs[1].get("description")
        assert desc is not None, "add_topic must be called with description"
        parsed_desc = json.loads(desc)
        assert isinstance(parsed_desc, list)
        assert parsed_desc[0]["chapter"] == "1. Introduction"
        assert mock_gs.add_concept.call_count == 6  # 2 chapters + 4 sections

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_rag_failure(self, mock_rag, mock_gs, mock_sf, _mock_resolve, mock_files):
        """RAG failure -> returns error string with hint."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        mock_rag.return_value = "Error: Open WebUI is unreachable"

        result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "Error" in result
        assert "Could not retrieve document content" in result

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_rag_no_relevant_content(self, mock_rag, mock_gs, mock_sf, _mock_resolve, mock_files):
        """RAG returns 'No relevant content' -> treated as failure with hint."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        mock_rag.return_value = "No relevant content found for query."

        result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "Error" in result
        assert "Could not retrieve document content" in result

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_llm_failure(self, mock_rag, mock_llm, mock_gs, mock_sf, _mock_resolve, mock_files):
        """LLM failure -> returns error string."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_rag.return_value = "Some book content here..."
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        mock_llm.return_value = "Error: LLM service unavailable"

        result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "Error" in result
        assert "Failed to analyze document structure" in result

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_json_validation_failure(self, mock_rag, mock_llm, mock_gs, mock_sf, _mock_resolve, mock_files):
        """JSON validation failure -> returns parse error."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_rag.return_value = "Some content"
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        mock_llm.return_value = "not valid json"

        result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "Error" in result
        assert "Could not parse" in result

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_json_validation_error_passthrough(
        self, mock_rag, mock_llm, mock_gs, mock_sf, _mock_resolve, mock_files,
    ):
        """Validation error -> returns detail from _parse_and_validate_plan."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_rag.return_value = "Some content"
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        # Valid JSON but too many chapters -> triggers Validation error
        data = [{"chapter": f"Ch{i}", "sections": ["s1"]} for i in range(51)]
        mock_llm.return_value = json.dumps(data)

        result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "Extracted structure is invalid" in result
        assert "Too many chapters" in result

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_llm_timeout(self, mock_rag, mock_llm, mock_gs, mock_sf, _mock_resolve, mock_files):
        """LLM call exceeding timeout -> returns timeout error."""
        import asyncio

        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_rag.return_value = "Some content"
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        async def slow_llm(*args, **kwargs):
            await asyncio.sleep(60)

        mock_llm.side_effect = slow_llm

        # Patch timeout to 0.01s so the test doesn't actually wait 30s
        with patch("app.tools.learning_plan_tool._LLM_TIMEOUT_SECONDS", 0.01):
            result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "Error" in result
        assert "timed out" in result

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value="uuid-1")
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_idempotent_existing_topic(self, mock_gs, mock_sf, _mock_resolve, mock_files):
        """Existing topic -> returns existing plan instead of creating duplicate."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_files.return_value = [{"filename": "Test Book.pdf"}]
        mock_gs.get_topic_by_name = AsyncMock(return_value={"id": 1, "name": "Test Book"})
        mock_gs.get_concepts_by_topic = AsyncMock(
            return_value=[
                {"id": 1, "name": "1. Intro", "topic_id": 1, "definition": None, "difficulty": None},
                {"id": 2, "name": "1.1 Start", "topic_id": 1, "definition": None, "difficulty": None},
            ]
        )

        result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "already exists" in result
        mock_gs.add_topic.assert_not_called()

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_atomic_rollback_on_db_error(self, mock_rag, mock_llm, mock_gs, mock_sf, _mock_resolve, mock_files):
        """DB error during write -> rollback, no dirty data."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        # First session call: idempotency check (no existing)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        mock_rag.return_value = "Content"
        mock_llm.return_value = _VALID_JSON
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

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

        result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "Error" in result
        assert "Failed to save learning plan" in result
        mock_session.rollback.assert_called_once()

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value="uuid-1")
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_idempotent_with_description_skips_format_from_db(self, mock_gs, mock_sf, _mock_resolve, mock_files):
        """Idempotent path with valid description JSON -> uses _format_plan, not _format_plan_from_db."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_files.return_value = [{"filename": "Test Book.pdf"}]
        mock_gs.get_topic_by_name = AsyncMock(
            return_value={"id": 1, "name": "Test Book", "description": _VALID_JSON}
        )

        result = await generate_learning_plan("Test Book", collection_name="test-kb")

        assert "already exists" in result
        assert "Chapter 1: 1. Introduction" in result
        assert "Chapter 2: 2. Core Topics" in result
        # Should NOT call get_concepts_by_topic because description JSON was sufficient
        mock_gs.get_concepts_by_topic.assert_not_called()
        mock_gs.add_topic.assert_not_called()

    async def test_empty_source_name(self):
        result = await generate_learning_plan("   ")
        assert "Error" in result
        assert "source_name is empty" in result

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_single_doc_rag_error_propagates(
        self, mock_rag, mock_gs, mock_sf, _mock_resolve, mock_files,
    ):
        """Single-file collection + RAG error -> error propagated to caller."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        mock_rag.return_value = "Error: Open WebUI is unreachable"

        result = await generate_learning_plan("Test Book", collection_name="explicit-kb")

        assert "Error" in result
        assert "Could not retrieve document content" in result


# --- Multi-doc tests ---


class TestMultiDocBatch:
    @patch("app.tools.learning_plan_tool._query_collection_raw", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool.get_chat_completion", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_multi_doc_batch_generates_per_file(
        self, mock_gs, mock_sf, _mock_resolve, mock_files, mock_llm, mock_raw
    ):
        """3-file collection -> generates independent topic for each file."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_gs.add_topic = AsyncMock(side_effect=lambda s, name, **kw: {"id": hash(name) % 1000, "name": name})
        mock_gs.add_concept = AsyncMock(return_value={"id": 1, "name": "c"})
        mock_gs.load_graph = AsyncMock()
        mock_gs.delete_topic_cascade = AsyncMock()

        mock_files.return_value = [
            {"filename": "Pro Git.pdf"},
            {"filename": "Pragmatic.pdf"},
            {"filename": "Tidy First.pdf"},
        ]

        # RAG returns chunks with matching metadata per file
        def make_raw(query, collection_names, k=20):
            docs = ["chapter content"] * 5
            metas = [{"name": "Pro Git.pdf"}] * 2 + [{"name": "Pragmatic.pdf"}] * 2 + [{"name": "Tidy First.pdf"}]
            dists = [0.1] * 5
            return (docs, metas, dists)

        mock_raw.side_effect = make_raw
        mock_llm.return_value = _VALID_JSON

        # source_name doesn't match any specific file -> batch mode
        result = await generate_learning_plan("All Books", collection_name="coll-uuid")

        assert "Generated learning plans" in result
        assert "Pro Git" in result
        assert "Pragmatic" in result
        assert "Tidy First" in result

    @patch("app.tools.learning_plan_tool._query_collection_raw", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool.get_chat_completion", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_multi_doc_source_name_matches_file(
        self, mock_gs, mock_sf, _mock_resolve, mock_files, mock_llm, mock_raw
    ):
        """source_name matches a file -> generates plan for that file only."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_gs.add_topic = AsyncMock(return_value={"id": 1, "name": "Pro Git"})
        mock_gs.add_concept = AsyncMock(return_value={"id": 1, "name": "c"})
        mock_gs.load_graph = AsyncMock()

        mock_files.return_value = [
            {"filename": "Pro Git.pdf"},
            {"filename": "Pragmatic.pdf"},
        ]

        mock_raw.return_value = (
            ["chapter content"] * 5,
            [{"name": "Pro Git.pdf"}] * 5,
            [0.1] * 5,
        )
        mock_llm.return_value = _VALID_JSON

        result = await generate_learning_plan("Pro Git", collection_name="coll-uuid")

        # Should generate plan for Pro Git only
        assert "Pro Git" in result
        # Should NOT batch generate for Pragmatic
        assert "Pragmatic" not in result

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_multi_doc_source_name_ambiguous(
        self, mock_gs, mock_sf, _mock_resolve, mock_files
    ):
        """source_name matches multiple files -> returns candidate list."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        mock_files.return_value = [
            {"filename": "Pro Git.pdf"},
            {"filename": "Git in Practice.pdf"},
        ]

        result = await generate_learning_plan("git", collection_name="coll-uuid")

        assert "Multiple documents match" in result
        assert "Pro Git.pdf" in result
        assert "Git in Practice.pdf" in result

    @patch("app.tools.learning_plan_tool._query_collection_raw", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool.get_chat_completion", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_multi_doc_skip_existing(
        self, mock_gs, mock_sf, _mock_resolve, mock_files, mock_llm, mock_raw
    ):
        """Already-existing topics are skipped in batch mode."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        # First file has existing topic, second doesn't
        call_count = {"n": 0}
        async def mock_get_topic(session, name):
            call_count["n"] += 1
            if name == "Pro Git":
                return {"id": 1, "name": "Pro Git", "description": _VALID_JSON}
            return None

        mock_gs.get_topic_by_name = AsyncMock(side_effect=mock_get_topic)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_gs.add_topic = AsyncMock(return_value={"id": 2, "name": "Pragmatic"})
        mock_gs.add_concept = AsyncMock(return_value={"id": 1, "name": "c"})
        mock_gs.load_graph = AsyncMock()

        mock_files.return_value = [
            {"filename": "Pro Git.pdf"},
            {"filename": "Pragmatic.pdf"},
        ]

        mock_raw.return_value = (
            ["chapter content"] * 5,
            [{"name": "Pragmatic.pdf"}] * 5,
            [0.1] * 5,
        )
        mock_llm.return_value = _VALID_JSON

        result = await generate_learning_plan("All", collection_name="coll-uuid")

        assert "already exists" in result
        assert "Pro Git" in result

    @patch("app.tools.learning_plan_tool._query_collection_raw", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_multi_doc_insufficient_chunks_skip(
        self, mock_gs, mock_sf, _mock_resolve, mock_files, mock_raw
    ):
        """Filtered chunks below minimum after both k=20 and k=40 -> file skipped."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        mock_files.return_value = [
            {"filename": "Pro Git.pdf"},
            {"filename": "Tiny.pdf"},
        ]

        # Both k=20 and k=40 retries return no matching chunks
        mock_raw.return_value = (
            ["chunk1"],
            [{"name": "Other.pdf"}],
            [0.1],
        )

        result = await generate_learning_plan("All", collection_name="coll-uuid")

        assert "insufficient content" in result

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_multi_doc_files_api_failure_reports_error(
        self, mock_gs, mock_sf, _mock_resolve, mock_files
    ):
        """Files API failure -> explicit error, no fallback to mixed RAG."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])

        mock_files.return_value = "Error: API returned 500"

        result = await generate_learning_plan("Test Book", collection_name="coll-uuid")

        assert "Cannot list documents" in result
        assert "temporarily unavailable" in result

    @patch("app.tools.learning_plan_tool._query_collection_raw", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool.get_chat_completion", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_multi_doc_single_file_failure_continues(
        self, mock_gs, mock_sf, _mock_resolve, mock_files, mock_llm, mock_raw
    ):
        """Single file RAG failure in batch -> marked error, others continue."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_gs.get_topic_by_name = AsyncMock(return_value=None)
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_gs.add_topic = AsyncMock(side_effect=lambda s, name, **kw: {"id": 1, "name": name})
        mock_gs.add_concept = AsyncMock(return_value={"id": 1, "name": "c"})
        mock_gs.load_graph = AsyncMock()

        mock_files.return_value = [
            {"filename": "Good Book.pdf"},
            {"filename": "Bad Book.pdf"},
        ]

        call_n = {"n": 0}
        def mock_raw_fn(query, collection_names, k=20):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return (
                    ["content"] * 5,
                    [{"name": "Good Book.pdf"}] * 5,
                    [0.1] * 5,
                )
            else:
                return "Error: timeout"

        mock_raw.side_effect = mock_raw_fn
        mock_llm.return_value = _VALID_JSON

        result = await generate_learning_plan("All", collection_name="coll-uuid")

        # Good Book succeeds, Bad Book fails
        assert "\u2705" in result or "Good Book" in result
        assert "\u274c" in result or "Bad Book" in result


# --- Force parameter tests ---


class TestForceParameter:
    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_force_single_doc_build_then_replace(
        self, mock_rag, mock_llm, mock_gs, mock_sf, _mock_resolve, mock_files
    ):
        """force=True -> generates new plan, then atomically replaces old one."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(
            return_value={"id": 42, "name": "Test Book", "description": _VALID_JSON}
        )
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        mock_rag.return_value = "Some content"
        mock_llm.return_value = _VALID_JSON

        mock_gs.delete_topic_cascade = AsyncMock()
        mock_gs.add_topic = AsyncMock(return_value={"id": 100, "name": "Test Book"})
        mock_gs.add_concept = AsyncMock(return_value={"id": 1, "name": "c"})
        mock_gs.load_graph = AsyncMock()
        # Data-loss guard: existing plan has fewer concepts than new → allow regeneration
        mock_gs.get_concepts_by_topic = AsyncMock(return_value=[{"name": "old"}])

        result = await generate_learning_plan("Test Book", collection_name="test-kb", force=True)

        assert "Learning Plan: Test Book" in result
        # Verify old topic was deleted
        mock_gs.delete_topic_cascade.assert_called_once()
        # Verify new topic was created
        mock_gs.add_topic.assert_called_once()

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_force_rag_failure_preserves_old(
        self, mock_rag, mock_gs, mock_sf, _mock_resolve, mock_files
    ):
        """force=True + RAG failure -> old plan preserved (build-then-replace)."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(
            return_value={"id": 42, "name": "Test Book", "description": _VALID_JSON}
        )
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        mock_rag.return_value = "Error: Open WebUI is unreachable"

        result = await generate_learning_plan("Test Book", collection_name="test-kb", force=True)

        assert "Error" in result
        # Old topic should NOT be deleted since RAG failed
        mock_gs.delete_topic_cascade.assert_not_called()

    @patch("app.tools.learning_plan_tool._fetch_collection_files", new_callable=AsyncMock)
    @patch("app.tools.learning_plan_tool._resolve_collection_name_to_id", new_callable=AsyncMock, return_value=None)
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    @patch("app.tools.learning_plan_tool.get_chat_completion")
    @patch("app.tools.learning_plan_tool.search_knowledge_base")
    async def test_force_llm_failure_preserves_old(
        self, mock_rag, mock_llm, mock_gs, mock_sf, _mock_resolve, mock_files
    ):
        """force=True + LLM failure -> old plan preserved."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(
            return_value={"id": 42, "name": "Test Book", "description": _VALID_JSON}
        )
        mock_gs.get_all_topics = AsyncMock(return_value=[])
        mock_files.return_value = [{"filename": "Test Book.pdf"}]

        mock_rag.return_value = "Some content"
        mock_llm.return_value = "Error: LLM service unavailable"

        result = await generate_learning_plan("Test Book", collection_name="test-kb", force=True)

        assert "Error" in result
        # Old topic should NOT be deleted since LLM failed
        mock_gs.delete_topic_cascade.assert_not_called()


# --- get_learning_plan tests ---


class TestGetLearningPlan:
    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_with_data(self, mock_gs, mock_sf):
        """Has data -> returns formatted plan."""
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
        """No plans -> returns friendly hint."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_all_topics = AsyncMock(return_value=[])

        result = await get_learning_plan()
        assert "No learning plans found" in result

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_specific_topic_not_found(self, mock_gs, mock_sf):
        """Named topic not found -> returns friendly hint."""
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
        """No topic_name -> list all plans with concept counts."""
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

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_with_description_json(self, mock_gs, mock_sf):
        """Topic with valid description JSON -> uses stored structure, skips DB reconstruction."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(
            return_value={"id": 1, "name": "Python Book", "description": _VALID_JSON}
        )

        result = await get_learning_plan(topic_name="Python Book")
        assert "Chapter 1: 1. Introduction" in result
        assert "Chapter 2: 2. Core Topics" in result
        assert "Existing plan" in result
        # Should NOT call get_concepts_by_topic
        mock_gs.get_concepts_by_topic.assert_not_called()

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_description_none_fallback(self, mock_gs, mock_sf):
        """Topic with description=None -> falls back to DB heuristic reconstruction."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(
            return_value={"id": 1, "name": "Legacy Book", "description": None}
        )
        mock_gs.get_concepts_by_topic = AsyncMock(
            return_value=[
                {"id": 1, "name": "1 Intro", "topic_id": 1, "definition": None, "difficulty": None},
                {"id": 2, "name": "1.1 Basics", "topic_id": 1, "definition": None, "difficulty": None},
            ]
        )

        result = await get_learning_plan(topic_name="Legacy Book")
        assert "Legacy Book" in result
        assert "Intro" in result
        # Must have called get_concepts_by_topic for fallback
        mock_gs.get_concepts_by_topic.assert_called_once_with(mock_session, 1)

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_description_invalid_json_fallback(self, mock_gs, mock_sf):
        """Topic with corrupted description JSON -> falls back to DB heuristic."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(
            return_value={"id": 1, "name": "Bad Book", "description": "not valid json{{{"}
        )
        mock_gs.get_concepts_by_topic = AsyncMock(
            return_value=[
                {"id": 1, "name": "1 Chapter One", "topic_id": 1, "definition": None, "difficulty": None},
            ]
        )

        result = await get_learning_plan(topic_name="Bad Book")
        assert "Bad Book" in result
        assert "Chapter One" in result
        mock_gs.get_concepts_by_topic.assert_called_once()

    @patch("app.tools.learning_plan_tool.async_session_factory")
    @patch("app.tools.learning_plan_tool.graph_service")
    async def test_description_wrong_structure_fallback(self, mock_gs, mock_sf):
        """Topic with valid JSON but wrong structure (no 'chapter' key) -> falls back to DB."""
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_gs.get_topic_by_name = AsyncMock(
            return_value={"id": 1, "name": "Odd Book", "description": json.dumps([{"title": "Ch1"}])}
        )
        mock_gs.get_concepts_by_topic = AsyncMock(
            return_value=[
                {"id": 1, "name": "1 Intro", "topic_id": 1, "definition": None, "difficulty": None},
            ]
        )

        result = await get_learning_plan(topic_name="Odd Book")
        assert "Odd Book" in result
        # Falls back because plan_data[0] has no "chapter" key
        mock_gs.get_concepts_by_topic.assert_called_once()
