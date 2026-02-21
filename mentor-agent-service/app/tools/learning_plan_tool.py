"""Learning plan tools — generate and retrieve structured learning plans from uploaded documents."""

import asyncio
import json
import logging
import time

from app.dependencies import async_session_factory
from app.services import graph_service
from app.services.llm_service import get_chat_completion
from app.tools.search_knowledge_base_tool import search_knowledge_base

logger = logging.getLogger(__name__)

TOC_ANALYSIS_PROMPT = """Analyze the following text from a book/document. Extract the chapter and section structure.

Return ONLY a JSON array:
[{{"chapter": "1. Introduction", "sections": ["1.1 Getting Started", "1.2 Basic Concepts"]}}]

Rules:
- Keep original numbering if present
- If no clear chapter/section structure, create logical groupings
- Each chapter must have >=1 section
- Max 50 chapters, max 30 sections per chapter
- Return ONLY valid JSON, no markdown

Text:
{toc_content}
"""

PLAN_LIMITS = {
    "max_chapters": 50,
    "max_sections_per_chapter": 30,
    "max_name_length": 200,
}

_RAG_TEXT_MAX_LENGTH = 8000
_LLM_TIMEOUT_SECONDS = 30


def _normalize_name(name: str) -> str:
    """Normalize a source name for storage and comparison."""
    return name.strip()


def _parse_and_validate_plan(text: str) -> list[dict] | str:
    """Parse LLM JSON output; return parsed list or error string."""
    # Strip ```json ... ``` wrappers if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        # Remove closing fence
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        return f"Error: Parse — Invalid JSON from LLM response: {exc}"

    if not isinstance(data, list):
        return "Error: Parse — Expected JSON array of chapters"

    if len(data) == 0:
        return "Error: Validation — No chapters found in the document structure"

    if len(data) > PLAN_LIMITS["max_chapters"]:
        return f"Error: Validation — Too many chapters ({len(data)} > {PLAN_LIMITS['max_chapters']})"

    validated = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return f"Error: Validation — Chapter {i + 1} is not an object"

        chapter_name = item.get("chapter")
        if not chapter_name or not isinstance(chapter_name, str) or not chapter_name.strip():
            return f"Error: Validation — Chapter {i + 1} missing or empty 'chapter' field"

        if len(chapter_name) > PLAN_LIMITS["max_name_length"]:
            return f"Error: Validation — Chapter name too long ({len(chapter_name)} > {PLAN_LIMITS['max_name_length']})"

        sections = item.get("sections", [])
        if not isinstance(sections, list):
            return f"Error: Validation — Chapter {i + 1} 'sections' must be a list"

        if len(sections) > PLAN_LIMITS["max_sections_per_chapter"]:
            return (
                f"Error: Validation — Chapter '{chapter_name}' has too many sections "
                f"({len(sections)} > {PLAN_LIMITS['max_sections_per_chapter']})"
            )

        # Deduplicate sections (keep first, warn)
        seen: set[str] = set()
        unique_sections: list[str] = []
        for sec in sections:
            if not isinstance(sec, str) or not sec.strip():
                continue
            if len(sec) > PLAN_LIMITS["max_name_length"]:
                return (
                    f"Error: Validation — Section name too long in chapter '{chapter_name}' "
                    f"({len(sec)} > {PLAN_LIMITS['max_name_length']})"
                )
            key = sec.strip().lower()
            if key not in seen:
                seen.add(key)
                unique_sections.append(sec.strip())
            else:
                logger.warning("Duplicate section '%s' in chapter '%s', keeping first", sec, chapter_name)

        if not unique_sections:
            logger.warning("Chapter '%s' has no valid sections after filtering", chapter_name)

        validated.append({"chapter": chapter_name.strip(), "sections": unique_sections})

    return validated


def _format_plan(source_name: str, chapters: list[dict], status: str = "Plan created") -> str:
    """Format a learning plan for display."""
    lines = [
        f"\U0001f4da Learning Plan: {source_name}",
        "\u2501" * 30,
        "",
    ]

    total_sections = 0
    for i, ch in enumerate(chapters, 1):
        lines.append(f"\U0001f4d6 Chapter {i}: {ch['chapter']}")
        for j, sec in enumerate(ch.get("sections", []), 1):
            lines.append(f"   \u2022 {i}.{j} {sec}")
            total_sections += 1
        lines.append("")

    lines.append("\u2501" * 30)
    lines.append(f"Total: {len(chapters)} chapters, {total_sections} sections")
    lines.append(f"Status: {status} \u2705")

    return "\n".join(lines)


def _is_section_name(name: str) -> bool:
    """Check if a concept name looks like a section (has sub-numbering like '1.1')."""
    first_token = name.split(" ", 1)[0].rstrip(".")
    # Must start with a digit and contain a dot (e.g., "1.1", "2.3.1")
    return bool(first_token) and first_token[0].isdigit() and "." in first_token


def _format_plan_from_db(source_name: str, concepts: list[dict]) -> str:
    """Format a plan from DB concepts for display."""
    # Group concepts into chapters and sections based on naming convention.
    # Chapters: names starting with a digit but no sub-dot (e.g., "1 Intro", "1. Intro")
    # Sections: names with sub-numbering (e.g., "1.1 Getting Started")
    # Non-numbered names: treated as chapters
    chapters: list[dict] = []
    current_chapter: dict | None = None
    orphan_sections: list[str] = []

    for c in concepts:
        name = c["name"]
        if _is_section_name(name):
            if current_chapter is not None:
                current_chapter["sections"].append(name)
            else:
                orphan_sections.append(name)
        else:
            # Attach any orphan sections to this chapter
            current_chapter = {"chapter": name, "sections": list(orphan_sections)}
            orphan_sections.clear()
            chapters.append(current_chapter)

    # Handle trailing orphan sections
    if orphan_sections:
        if current_chapter is not None:
            current_chapter["sections"].extend(orphan_sections)
        else:
            # All concepts are sections with no chapter — treat each as chapter
            chapters = [{"chapter": s, "sections": []} for s in orphan_sections]

    if not chapters:
        # Fallback: treat all concepts as chapters
        chapters = [{"chapter": c["name"], "sections": []} for c in concepts]

    return _format_plan(source_name, chapters, status="Existing plan")


async def generate_learning_plan(
    source_name: str,
    query: str | None = None,
    collection_names: list[str] | None = None,
) -> str:
    """Generate a structured learning plan from an uploaded document.

    Fail Soft: all errors return error strings, never raise.
    """
    start_time = time.monotonic()
    logger.info("generate_learning_plan start source=%s", source_name)

    try:
        # 1. Normalize name
        normalized_name = _normalize_name(source_name)
        if not normalized_name:
            return "Error: source_name is empty. Hint: Provide the name of the book or document."

        # 2-4. Idempotency check
        async with async_session_factory() as session:
            existing = await graph_service.get_topic_by_name(session, normalized_name)
            if existing is None:
                # Also try case-insensitive match
                all_topics = await graph_service.get_all_topics(session)
                for t in all_topics:
                    if t["name"].strip().lower() == normalized_name.lower():
                        existing = t
                        break

            if existing is not None:
                concepts = await graph_service.get_concepts_by_topic(session, existing["id"])
                plan_text = _format_plan_from_db(existing["name"], concepts)
                logger.info(
                    "generate_learning_plan idempotent hit source=%s topic_id=%d",
                    source_name,
                    existing["id"],
                )
                return (
                    f"Learning plan for '{source_name}' already exists:\n"
                    f"{plan_text}\n"
                    f"Use get_learning_plan to view details."
                )

        # 5. RAG retrieval
        search_query = query or f"table of contents overview introduction chapters {source_name}"
        toc_text = await search_knowledge_base(
            query=search_query,
            collection_names=collection_names,
            k=8,
        )

        if toc_text.startswith("Error") or toc_text.startswith("No relevant content"):
            logger.warning("generate_learning_plan failed stage=rag source=%s error=%s", source_name, toc_text)
            return (
                f"Error: Could not retrieve document content for '{source_name}'. "
                "Hint: Ensure the document is uploaded to Open WebUI and try again."
            )

        logger.info("generate_learning_plan rag_result len=%d", len(toc_text))

        # Truncate if too long
        if len(toc_text) > _RAG_TEXT_MAX_LENGTH:
            toc_text = toc_text[:_RAG_TEXT_MAX_LENGTH] + "\n[truncated]"

        # 7. LLM analysis (with sub-step timeout)
        prompt = TOC_ANALYSIS_PROMPT.format(toc_content=toc_text)
        try:
            plan_json = await asyncio.wait_for(
                get_chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2000,
                ),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("generate_learning_plan failed stage=llm source=%s error=timeout(%ds)", source_name, _LLM_TIMEOUT_SECONDS)
            return (
                "Error: LLM analysis timed out. "
                "Hint: The service may be busy — please try again in a moment."
            )

        if plan_json.startswith("Error"):
            logger.warning("generate_learning_plan failed stage=llm source=%s error=%s", source_name, plan_json)
            return (
                "Error: Failed to analyze document structure. "
                "Hint: The document may not have a clear table of contents. Try providing a custom query."
            )

        # 9. Parse and validate
        parsed = _parse_and_validate_plan(plan_json)
        if isinstance(parsed, str):
            logger.warning("generate_learning_plan failed stage=parse source=%s error=%s", source_name, parsed)
            if "Validation" in parsed:
                detail = parsed.split("—", 1)[-1].strip() if "—" in parsed else parsed
                return (
                    f"Error: Extracted structure is invalid ({detail}). "
                    "Hint: Try again or provide a custom query to help the LLM find better content."
                )
            return (
                "Error: Could not parse the chapter structure from LLM response. "
                "Hint: Try again — LLM output varies between calls."
            )

        # 11-22. Atomic write to DB
        async with async_session_factory() as session:
            try:
                topic = await graph_service.add_topic(
                    session,
                    normalized_name,
                    source_material=normalized_name,
                    auto_commit=False,
                )

                total_concepts = 0
                ch_count = len(parsed)
                for ch in parsed:
                    await graph_service.add_concept(
                        session,
                        ch["chapter"],
                        topic_id=topic["id"],
                        auto_commit=False,
                    )
                    total_concepts += 1
                    for sec in ch.get("sections", []):
                        await graph_service.add_concept(
                            session,
                            sec,
                            topic_id=topic["id"],
                            auto_commit=False,
                        )
                        total_concepts += 1

                await session.commit()
                await graph_service.load_graph(session)

                elapsed = time.monotonic() - start_time
                logger.info(
                    "generate_learning_plan stored topic_id=%d concepts=%d elapsed=%.1fs",
                    topic["id"],
                    total_concepts,
                    elapsed,
                )

                return _format_plan(source_name, parsed)

            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "generate_learning_plan failed stage=db source=%s error=%s",
                    source_name,
                    exc,
                )
                return "Error: Failed to save learning plan to database. Hint: This is an internal error — please try again."

    except Exception as exc:
        logger.warning("generate_learning_plan failed stage=unexpected source=%s error=%s", source_name, exc)
        return f"Error: Unexpected error generating learning plan — {exc}"


async def get_learning_plan(topic_name: str | None = None) -> str:
    """Retrieve learning plan(s) from the knowledge graph.

    Fail Soft: all errors return error strings, never raise.
    """
    try:
        async with async_session_factory() as session:
            if topic_name:
                # Find specific topic
                normalized = _normalize_name(topic_name)
                topic = await graph_service.get_topic_by_name(session, normalized)

                # Case-insensitive fallback
                if topic is None:
                    all_topics = await graph_service.get_all_topics(session)
                    for t in all_topics:
                        if t["name"].strip().lower() == normalized.lower():
                            topic = t
                            break

                if topic is None:
                    return (
                        f"No learning plan found for '{topic_name}'. "
                        "Hint: Use generate_learning_plan to create one first, "
                        "or call get_learning_plan without arguments to see all plans."
                    )

                concepts = await graph_service.get_concepts_by_topic(session, topic["id"])
                if not concepts:
                    return f"Learning plan '{topic['name']}' exists but has no concepts yet."

                return _format_plan_from_db(topic["name"], concepts)

            else:
                # List all topics with concept counts
                topics = await graph_service.get_all_topics(session)
                if not topics:
                    return (
                        "No learning plans found. "
                        "Hint: Upload a document and use generate_learning_plan to create one."
                    )

                lines = ["\U0001f4da Your Learning Plans", "\u2501" * 30, ""]
                for t in topics:
                    concepts = await graph_service.get_concepts_by_topic(session, t["id"])
                    lines.append(f"\U0001f4d6 {t['name']} — {len(concepts)} concepts")
                lines.append("")
                lines.append("\u2501" * 30)
                lines.append(f"Total: {len(topics)} plans")
                lines.append("Use get_learning_plan(topic_name='...') to view details.")

                return "\n".join(lines)

    except Exception as exc:
        logger.warning("get_learning_plan failed error=%s", exc)
        return f"Error: Failed to retrieve learning plan — {exc}"
