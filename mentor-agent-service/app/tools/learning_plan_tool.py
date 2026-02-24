"""Learning plan tools — generate and retrieve structured learning plans from uploaded documents."""

import asyncio
import json
import logging
import re
import time

from app.config import get_providers
from app.dependencies import async_session_factory
from app.services import graph_service
from app.services.llm_service import get_chat_completion
from app.tools.search_knowledge_base_tool import (
    _extract_filenames,
    _fetch_collection_files,
    _query_collection_raw,
    _resolve_collection_name_to_id,
    search_knowledge_base,
)

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
_MIN_CHUNKS_FOR_PLAN = 2
_MAX_BATCH_FILES = 10


def _normalize_name(name: str) -> str:
    """Normalize a source name for storage and comparison."""
    return name.strip()


def _clean_filename(filename: str) -> str:
    """Remove file extension for use as topic name. 'Pro Git.pdf' -> 'Pro Git'"""
    if "." in filename:
        return filename.rsplit(".", 1)[0].strip()
    return filename.strip()


def _match_filename(source_name: str, filenames: list[str]) -> str | list[str] | None:
    """Match source_name against filenames.

    Returns:
        str — unique match
        list[str] — multiple candidates (ambiguous)
        None — no match
    """
    normalized = source_name.strip().lower()

    # Pass 1: exact match (with/without extension)
    exact = []
    for fname in filenames:
        if fname.strip().lower() == normalized:
            return fname  # exact full match
        stem = fname.rsplit(".", 1)[0].strip().lower() if "." in fname else fname.strip().lower()
        if stem == normalized:
            exact.append(fname)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact  # ambiguous

    # Pass 2: substring match — collect all candidates
    candidates = [f for f in filenames if normalized in f.strip().lower()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return candidates  # ambiguous

    return None


def _stem(filename: str) -> str:
    """Extract stem (name without extension) in lowercase. 'Pro Git.pdf' -> 'pro git'"""
    name = filename.strip().lower()
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name.strip()


def _filter_chunks_by_source(
    docs: list[str], metas: list[dict], dists: list[float], target_filename: str
) -> tuple[list[str], list[dict], list[float]]:
    """Filter RAG chunks where metadata name/source matches target_filename.

    Matching strategy (case-insensitive, any of):
      1. Stem-equal: stem(target) == stem(metadata name)
      2. Bidirectional containment on stem: stem(target) in stem(name) or vice versa
      3. Target stem found in source path (for path-style metadata)
    """
    target_s = _stem(target_filename)
    if not target_s:
        return [], [], []

    filtered_docs = []
    filtered_metas = []
    filtered_dists = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta_name = (meta.get("name") or "").strip().lower()
        meta_source = (meta.get("source") or "").strip().lower()
        name_s = _stem(meta_name) if meta_name else ""

        matched = (
            # Stem equality
            (name_s and name_s == target_s)
            # Bidirectional containment on stems
            or (name_s and (target_s in name_s or name_s in target_s))
            # Target stem in source path
            or (meta_source and target_s in meta_source)
        )
        if matched:
            filtered_docs.append(doc)
            filtered_metas.append(meta)
            filtered_dists.append(dist)
    return filtered_docs, filtered_metas, filtered_dists


def _format_ambiguous_matches(source_name: str, candidates: list[str]) -> str:
    """Format ambiguous match error with candidate list for user selection."""
    lines = [
        f"Multiple documents match '{source_name}':",
    ]
    for c in candidates:
        lines.append(f"  - {c}")
    lines.append("")
    lines.append(
        "Hint: Call generate_learning_plan again with source_name "
        "set to the exact filename."
    )
    return "\n".join(lines)


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


async def _resolve_plan_display(topic: dict, session, *, status: str = "Existing plan") -> str:
    """Resolve the best display for a topic's learning plan.

    Prefers the stored JSON in topic.description (generation-time snapshot).
    Falls back to DB heuristic reconstruction for legacy topics (description=None).

    Note: description is a generation-time snapshot. If concept editing is added
    in the future, description must be cleared or updated to avoid drift.
    """
    desc = topic.get("description")
    if desc:
        try:
            plan_data = json.loads(desc)
            if (
                isinstance(plan_data, list)
                and plan_data
                and isinstance(plan_data[0], dict)
                and "chapter" in plan_data[0]
            ):
                return _format_plan(topic["name"], plan_data, status=status)
        except (json.JSONDecodeError, ValueError):
            pass
    # Fallback: legacy topic without stored JSON
    concepts = await graph_service.get_concepts_by_topic(session, topic["id"])
    if not concepts:
        return f"Learning plan '{topic['name']}' exists but has no concepts yet."
    return _format_plan_from_db(topic["name"], concepts)


def _tokenize_name(name: str) -> set[str]:
    """Extract meaningful word tokens from a topic name for fuzzy comparison.

    Strips punctuation, lowercases, and removes common noise tokens (site domains,
    single-char tokens like initials). The resulting set is order-independent,
    so "Ousterhout, John" and "John K. Ousterhout" produce equivalent sets.

    Examples:
        "A Philosophy of Software Design, 2nd Edition (Ousterhout, John) (z-library.sk, 1lib.sk)"
        -> {"philosophy", "software", "design", "2nd", "edition", "ousterhout", "john", ...}
    """
    # Noise domains that appear in z-library download filenames
    _NOISE_TOKENS = {"z-library", "1lib", "z-lib", "sk", "org", "com"}
    # Split on non-alphanumeric (except hyphens within words)
    raw_tokens = re.findall(r"[a-zA-Z0-9][\w-]*[a-zA-Z0-9]|[a-zA-Z0-9]", name.lower())
    return {t for t in raw_tokens if len(t) > 1 and t not in _NOISE_TOKENS}


def _name_similarity(name_a: str, name_b: str) -> float:
    """Jaccard similarity between tokenized names. Returns 0.0-1.0."""
    tokens_a = _tokenize_name(name_a)
    tokens_b = _tokenize_name(name_b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


# Threshold for Pass 4 fuzzy match. 0.8 is strict enough to avoid matching
# genuinely different books while tolerating author name reordering, middle
# initials, and site-domain noise.
_FUZZY_MATCH_THRESHOLD = 0.8


async def _find_existing_topic(session, normalized_name: str) -> dict | None:
    """Find topic by exact name, case-insensitive, substring, then fuzzy fallback."""
    # Pass 1: exact name match
    existing = await graph_service.get_topic_by_name(session, normalized_name)
    if existing is not None:
        return existing

    # Pass 2: case-insensitive exact match
    query_lower = normalized_name.lower()
    all_topics = await graph_service.get_all_topics(session)
    for t in all_topics:
        if t["name"].strip().lower() == query_lower:
            return t

    # Pass 3: substring match (e.g., "Tidy First" matches "Tidy First?")
    candidates = [
        t for t in all_topics
        if query_lower in t["name"].strip().lower()
        or t["name"].strip().lower() in query_lower
    ]
    if len(candidates) == 1:
        return candidates[0]

    # Pass 4: fuzzy word-set match — handles author name reordering,
    # middle initials, punctuation differences.
    # e.g., "Book (Ousterhout, John)" matches "Book (John K. Ousterhout)"
    fuzzy_candidates = [
        t for t in all_topics
        if _name_similarity(normalized_name, t["name"]) >= _FUZZY_MATCH_THRESHOLD
    ]
    if len(fuzzy_candidates) == 1:
        return fuzzy_candidates[0]

    return None


async def _write_plan_to_db(
    session, topic_name: str, parsed: list[dict], *, old_topic_id: int | None = None
) -> dict:
    """Atomic DB write: optionally delete old topic, then create new topic + concepts.

    Returns the new topic dict. Caller must handle commit/rollback.
    """
    if old_topic_id is not None:
        await graph_service.delete_topic_cascade(session, old_topic_id, auto_commit=False)

    topic = await graph_service.add_topic(
        session,
        topic_name,
        description=json.dumps(parsed, ensure_ascii=False),
        source_material=topic_name,
        auto_commit=False,
    )

    total_concepts = 0
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

    return topic


async def _run_llm_analysis(toc_text: str) -> str | list[dict]:
    """Run LLM TOC analysis and parse result. Returns parsed list or error string."""
    if len(toc_text) > _RAG_TEXT_MAX_LENGTH:
        toc_text = toc_text[:_RAG_TEXT_MAX_LENGTH] + "\n[truncated]"

    prompt = TOC_ANALYSIS_PROMPT.format(toc_content=toc_text)
    try:
        plan_json = await asyncio.wait_for(
            get_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                provider=get_providers()[0],
                max_tokens=2000,
            ),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return (
            "Error: LLM analysis timed out. "
            "Hint: The service may be busy — please try again in a moment."
        )

    if plan_json.startswith("Error"):
        return (
            "Error: Failed to analyze document structure. "
            "Hint: The document may not have a clear table of contents. Try providing a custom query."
        )

    parsed = _parse_and_validate_plan(plan_json)
    if isinstance(parsed, str):
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

    return parsed


async def _generate_plan_for_file(
    filename: str,
    collection_uuid: str,
    query: str | None,
    force: bool,
    *,
    topic_name_override: str | None = None,
) -> str:
    """Generate a learning plan for a single file within a multi-doc collection.

    Args:
        topic_name_override: If provided, use this as the topic name instead of
            deriving from filename. Used by batch mode to pass dedup'd names.
    """
    original_stem = _clean_filename(filename)
    topic_name = topic_name_override or original_stem
    if not topic_name:
        return f"Error: empty filename after cleaning '{filename}'"

    # Idempotency check
    old_topic_id = None
    async with async_session_factory() as session:
        existing = await _find_existing_topic(session, topic_name)
        if existing is not None:
            if not force:
                return "skip_existing"
            old_topic_id = existing["id"]

    # RAG search: always use original stem (not dedup'd override like "Book (2)")
    search_query = query or f"table of contents chapters {original_stem}"
    f_docs: list[str] = []
    f_metas: list[dict] = []
    f_dists: list[float] = []

    for attempt_k in (20, 40):
        raw = await _query_collection_raw(
            query=search_query,
            collection_names=[collection_uuid],
            k=attempt_k,
        )
        if isinstance(raw, str):
            return f"Error: RAG failed for '{topic_name}': {raw}"

        docs, metas, dists = raw
        f_docs, f_metas, f_dists = _filter_chunks_by_source(docs, metas, dists, filename)

        logger.info(
            "_generate_plan_for_file file=%s k=%d raw=%d filtered=%d",
            filename, attempt_k, len(docs), len(f_docs),
        )

        if len(f_docs) >= _MIN_CHUNKS_FOR_PLAN:
            break

        if attempt_k == 20 and docs:
            meta_names = {(m.get("name") or m.get("source") or "?") for m in metas[:5]}
            logger.warning(
                "_generate_plan_for_file insufficient after k=%d for '%s' "
                "(need %d, got %d). Sample meta names: %s. Retrying with k=%d.",
                attempt_k, filename, _MIN_CHUNKS_FOR_PLAN,
                len(f_docs), meta_names, 40,
            )

    if len(f_docs) < _MIN_CHUNKS_FOR_PLAN:
        return "insufficient_chunks"

    # Combine filtered docs for LLM
    toc_text = "\n\n".join(f_docs)

    # LLM analysis
    parsed = await _run_llm_analysis(toc_text)
    if isinstance(parsed, str):
        return parsed  # error string

    # Data-loss guard: abort if regeneration would lose concepts
    if old_topic_id is not None:
        new_concept_count = sum(1 + len(ch.get("sections", [])) for ch in parsed)
        async with async_session_factory() as session:
            old_concepts = await graph_service.get_concepts_by_topic(session, old_topic_id)
        if len(old_concepts) > new_concept_count:
            logger.warning(
                "_generate_plan_for_file data-loss guard: existing=%d > new=%d for '%s'",
                len(old_concepts), new_concept_count, topic_name,
            )
            return "data_loss_guard"

    # Atomic DB write (build-then-replace)
    async with async_session_factory() as session:
        try:
            await _write_plan_to_db(
                session, topic_name, parsed, old_topic_id=old_topic_id
            )
            await session.commit()
            await graph_service.load_graph(session)
        except Exception as exc:
            await session.rollback()
            logger.warning("_generate_plan_for_file db error file=%s: %s", filename, exc)
            return f"Error: Failed to save learning plan for '{topic_name}': {exc}"

    # Return summary info
    total_sections = sum(len(ch.get("sections", [])) for ch in parsed)
    return f"ok:{len(parsed)}:{total_sections}"


async def _generate_plans_batch(
    filenames: list[str],
    collection_uuid: str,
    query: str | None,
    force: bool,
    collection_display_name: str,
) -> str:
    """Generate learning plans for multiple files in a collection."""
    # Limit batch size
    truncated = False
    if len(filenames) > _MAX_BATCH_FILES:
        filenames = filenames[:_MAX_BATCH_FILES]
        truncated = True

    # Topic name dedup tracking
    used_names: set[str] = set()
    name_map: dict[str, str] = {}  # filename -> topic_name
    for fname in filenames:
        clean = _clean_filename(fname)
        if clean.lower() in used_names:
            suffix = 2
            while f"{clean} ({suffix})".lower() in used_names:
                suffix += 1
            clean = f"{clean} ({suffix})"
        used_names.add(clean.lower())
        name_map[fname] = clean

    results: list[str] = []
    for fname in filenames:
        try:
            result = await _generate_plan_for_file(
                fname, collection_uuid, query, force,
                topic_name_override=name_map[fname],
            )
            if result == "skip_existing":
                results.append(f"\u23ed\ufe0f {name_map[fname]} — already exists (use force=true to regenerate)")
            elif result == "data_loss_guard":
                results.append(f"\u26a0\ufe0f {name_map[fname]} — regeneration aborted (new plan has fewer concepts)")
            elif result == "insufficient_chunks":
                results.append(f"\u274c {name_map[fname]} — insufficient content found")
            elif result.startswith("ok:"):
                parts = result.split(":")
                ch_count = parts[1]
                sec_count = parts[2]
                results.append(f"\u2705 {name_map[fname]} — {ch_count} chapters, {sec_count} sections")
            else:
                # Error string
                results.append(f"\u274c {name_map[fname]} — {result}")
        except Exception as exc:
            logger.warning("_generate_plans_batch file=%s error=%s", fname, exc)
            results.append(f"\u274c {name_map[fname]} — unexpected error: {exc}")

    lines = [f'\U0001f4da Generated learning plans for collection "{collection_display_name}":', ""]
    lines.extend(results)
    if truncated:
        lines.append(f"\n(Showing first {_MAX_BATCH_FILES} files; remaining files were skipped)")
    lines.append("")
    lines.append('Use get_learning_plan(topic_name="...") to view details.')

    return "\n".join(lines)


async def generate_learning_plan(
    source_name: str,
    query: str | None = None,
    collection_name: str = "",
    force: bool = False,
) -> str:
    """Generate a structured learning plan from an uploaded document.

    Fail Soft: all errors return error strings, never raise.
    """
    start_time = time.monotonic()
    logger.info("generate_learning_plan start source=%s force=%s", source_name, force)

    try:
        # 1. Normalize name
        normalized_name = _normalize_name(source_name)
        if not normalized_name:
            return "Error: source_name is empty. Hint: Provide the name of the book or document."

        # 2. Resolve collection name -> UUID
        collection_display_name = ""
        resolved_id = await _resolve_collection_name_to_id(collection_name)
        if resolved_id:
            logger.info(
                "generate_learning_plan: resolved name=%s -> id=%s",
                collection_name, resolved_id,
            )
            collection_display_name = collection_name
            collection_name = resolved_id
        else:
            # Not a known name — might already be a UUID, pass through
            logger.info(
                "generate_learning_plan: collection_name=%s "
                "not found by name, using as-is",
                collection_name,
            )

        # 3. Multi-doc detection — check files in collection
        collection_uuid = collection_name
        if collection_uuid:
            files = await _fetch_collection_files(collection_uuid)

            # Fail Soft: files API failure -> explicit error (no fallback to mixed RAG)
            if isinstance(files, str):
                return (
                    "Error: Cannot list documents in this collection — "
                    "per-document plan generation is temporarily unavailable. "
                    "Hint: Retry later or check Open WebUI files endpoint availability."
                )

            filenames = _extract_filenames(files)

            if not filenames:
                return (
                    "Error: No documents found in this collection. "
                    "Hint: Upload documents to the knowledge base in Open WebUI first."
                )

            if len(filenames) > 1:
                # Multi-doc collection
                matched = _match_filename(source_name, filenames)
                if isinstance(matched, list):
                    # Ambiguous match
                    return _format_ambiguous_matches(source_name, matched)
                elif isinstance(matched, str):
                    # Single file match — generate for that file only
                    result = await _generate_plan_for_file(
                        matched, collection_uuid, query, force
                    )
                    if result == "skip_existing":
                        clean = _clean_filename(matched)
                        async with async_session_factory() as session:
                            existing = await _find_existing_topic(session, clean)
                            if existing:
                                plan_text = await _resolve_plan_display(existing, session)
                                return (
                                    f"Learning plan for '{clean}' already exists:\n"
                                    f"{plan_text}\n"
                                    f"Use get_learning_plan to view details."
                                )
                        return f"Learning plan for '{clean}' already exists."
                    elif result == "insufficient_chunks":
                        return (
                            f"Error: Insufficient content found for '{matched}' in the collection. "
                            "Hint: The document may not have enough indexed content."
                        )
                    elif result.startswith("ok:"):
                        clean = _clean_filename(matched)
                        elapsed = time.monotonic() - start_time
                        logger.info("generate_learning_plan single-file done file=%s elapsed=%.1fs", matched, elapsed)
                        async with async_session_factory() as session:
                            topic = await _find_existing_topic(session, clean)
                            if topic:
                                return await _resolve_plan_display(topic, session, status="Plan created")
                        return _format_plan(clean, [], status="Plan created")
                    else:
                        return result  # error string
                else:
                    # No match — batch mode for all files
                    return await _generate_plans_batch(
                        filenames, collection_uuid, query, force,
                        collection_display_name or collection_uuid,
                    )
            # Single file or empty — fall through to single-doc behavior

        # 4. Single-doc idempotency check
        old_topic_id = None
        async with async_session_factory() as session:
            existing = await _find_existing_topic(session, normalized_name)

            if existing is not None:
                if not force:
                    plan_text = await _resolve_plan_display(existing, session)
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
                # force=True: record old topic for later replacement
                old_topic_id = existing["id"]
                logger.info(
                    "generate_learning_plan force=True, will replace topic_id=%d",
                    old_topic_id,
                )

        # 5. RAG retrieval (single-doc path)
        search_query = query or f"table of contents overview introduction chapters {source_name}"
        toc_text = await search_knowledge_base(
            query=search_query,
            collection_name=collection_name,
            k=8,
        )

        if toc_text.startswith("Error") or toc_text.startswith("No relevant content"):
            logger.warning("generate_learning_plan failed stage=rag source=%s error=%s", source_name, toc_text)
            return (
                f"Error: Could not retrieve document content for '{source_name}'. "
                "Hint: Ensure the document is uploaded to Open WebUI and try again."
            )

        logger.info("generate_learning_plan rag_result len=%d", len(toc_text))

        # 6. LLM analysis
        parsed = await _run_llm_analysis(toc_text)
        if isinstance(parsed, str):
            logger.warning("generate_learning_plan failed stage=llm/parse source=%s error=%s", source_name, parsed)
            return parsed

        # 7. Data-loss guard: abort if regeneration would lose concepts
        if old_topic_id is not None:
            new_concept_count = sum(1 + len(ch.get("sections", [])) for ch in parsed)
            async with async_session_factory() as session:
                old_concepts = await graph_service.get_concepts_by_topic(session, old_topic_id)
            if len(old_concepts) > new_concept_count:
                logger.warning(
                    "generate_learning_plan data-loss guard: existing=%d > new=%d, aborting for '%s'",
                    len(old_concepts), new_concept_count, source_name,
                )
                return (
                    f"Regeneration aborted: existing plan has {len(old_concepts)} concepts "
                    f"but the new plan would only have {new_concept_count}. "
                    f"This would result in data loss. The existing plan is preserved.\n"
                    f"Hint: Use get_learning_plan(topic_name='{source_name}') to view the current plan."
                )

        # 8. Atomic write to DB (build-then-replace for force)
        async with async_session_factory() as session:
            try:
                await _write_plan_to_db(
                    session, normalized_name, parsed, old_topic_id=old_topic_id
                )
                await session.commit()
                await graph_service.load_graph(session)

                elapsed = time.monotonic() - start_time
                logger.info(
                    "generate_learning_plan stored source=%s elapsed=%.1fs",
                    source_name,
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
                return (
                    "Error: Failed to save learning plan to database. "
                    "Hint: This is an internal error — please try again."
                )

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
                topic = await _find_existing_topic(session, normalized)

                if topic is None:
                    # List available names so LLM can self-correct
                    all_topics = await graph_service.get_all_topics(session)
                    available = [t["name"] for t in all_topics]
                    if available:
                        names_str = ", ".join(f"'{n}'" for n in available)
                        return (
                            f"No learning plan found for '{topic_name}'. "
                            f"Available plans: {names_str}. "
                            f"Hint: Call get_learning_plan with the exact topic_name from the list above."
                        )
                    return (
                        f"No learning plan found for '{topic_name}'. "
                        "No plans exist yet."
                    )

                return await _resolve_plan_display(topic, session)

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
