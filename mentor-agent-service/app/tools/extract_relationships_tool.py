"""Extract concept relationships tool — LLM-driven relationship discovery for knowledge graph."""

import asyncio
import json
import logging
import time

from app.config import get_providers
from app.dependencies import async_session_factory
from app.services import graph_service
from app.services.llm_service import get_chat_completion

logger = logging.getLogger(__name__)

RELATIONSHIP_EXTRACTION_PROMPT = """\
Analyze the following list of concepts from a learning material. \
Identify relationships between them.

There are two types of relationships:
1. **prerequisite**: Concept A requires understanding of Concept B first (A depends on B).
   Example: "Object-Oriented Programming" requires "Variables and Data Types"
2. **related**: Concepts that are thematically connected but neither depends on the other.
   Example: "Lists" is related to "Dictionaries" (both are data structures)

Rules:
- Only identify clear, meaningful relationships — do NOT create relationships between every pair
- For prerequisite: source is the advanced concept, target is the foundational concept
- Use exact concept names as provided in the list below
- Return ONLY valid JSON, no markdown code fences, no explanations
- Maximum 200 relationships

Return a JSON array:
[{{"source": "Advanced Concept Name", "target": "Foundational Concept Name", "type": "prerequisite"}},
 {{"source": "Concept A", "target": "Concept B", "type": "related"}}]

If no meaningful relationships can be identified, return an empty array: []

Concepts:
{concepts}
"""

RELATIONSHIP_LIMITS = {
    "max_relationships": 200,
}
VALID_RELATIONSHIP_TYPES = {"prerequisite", "related"}

_LLM_TIMEOUT_SECONDS = 30


def _parse_and_validate_relationships(
    text: str, valid_concept_names: dict[str, int]
) -> list[dict] | str:
    """Parse LLM JSON output; return parsed list or error string.

    Args:
        text: LLM raw output text
        valid_concept_names: {normalized_name: concept_id} mapping

    Returns:
        list[dict]: each with source_id, target_id, type, source_name, target_name
        str: error message (Fail Soft)
    """
    # Strip ```json ... ``` wrappers if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        return f"Error: Parse — Could not parse relationships from LLM response: {exc}"

    if not isinstance(data, list):
        return "Error: Parse — Expected JSON array of relationships"

    if len(data) > RELATIONSHIP_LIMITS["max_relationships"]:
        return (
            f"Error: Validation — Too many relationships "
            f"({len(data)} > {RELATIONSHIP_LIMITS['max_relationships']})"
        )

    seen: set[tuple[int, int, str]] = set()
    validated: list[dict] = []
    skipped_malformed = 0
    skipped_invalid_type = 0

    for item in data:
        if not isinstance(item, dict):
            skipped_malformed += 1
            continue

        source_name = item.get("source")
        target_name = item.get("target")
        rel_type = item.get("type")

        if not source_name or not isinstance(source_name, str):
            skipped_malformed += 1
            continue
        if not target_name or not isinstance(target_name, str):
            skipped_malformed += 1
            continue
        if not rel_type or rel_type not in VALID_RELATIONSHIP_TYPES:
            skipped_invalid_type += 1
            logger.warning("extract_relationships: invalid relationship type '%s', skipping", rel_type)
            continue

        source_key = source_name.strip().lower()
        target_key = target_name.strip().lower()

        source_id = valid_concept_names.get(source_key)
        target_id = valid_concept_names.get(target_key)

        if source_id is None:
            logger.warning("extract_relationships: unknown source concept '%s', skipping", source_name)
            continue
        if target_id is None:
            logger.warning("extract_relationships: unknown target concept '%s', skipping", target_name)
            continue

        # Filter self-referencing edges
        if source_id == target_id:
            continue

        # Deduplicate
        edge_key = (source_id, target_id, rel_type)
        if edge_key in seen:
            continue
        seen.add(edge_key)

        validated.append({
            "source_id": source_id,
            "target_id": target_id,
            "type": rel_type,
            "source_name": source_name.strip(),
            "target_name": target_name.strip(),
        })

    if skipped_malformed or skipped_invalid_type:
        logger.warning(
            "extract_relationships: validation skipped=%d malformed, %d invalid_type out of %d items",
            skipped_malformed, skipped_invalid_type, len(data),
        )

    # If LLM returned items but ALL were filtered out due to schema issues, that's a Validation error
    if len(data) > 0 and len(validated) == 0 and (skipped_malformed > 0 or skipped_invalid_type > 0):
        return (
            f"Error: Validation — All {len(data)} relationships from LLM were invalid "
            f"({skipped_malformed} malformed, {skipped_invalid_type} invalid type)."
        )

    return validated


def _format_relationships_output(
    topic_name: str,
    relationships: list[dict],
    created_count: int,
    skipped_count: int,
) -> str:
    """Format extracted relationships for display."""
    prereqs = [r for r in relationships if r["type"] == "prerequisite"]
    related = [r for r in relationships if r["type"] == "related"]

    lines = [
        f"\U0001f517 Concept Relationships: {topic_name}",
        "\u2501" * 30,
        "",
    ]

    if prereqs:
        lines.append("\U0001f4cc Prerequisites (A \u2192 B means \"A requires B\"):")
        for r in prereqs:
            lines.append(f"   \u2022 {r['source_name']} \u2192 {r['target_name']}")
        lines.append("")

    if related:
        lines.append("\U0001f517 Related:")
        for r in related:
            lines.append(f"   \u2022 {r['source_name']} \u2194 {r['target_name']}")
        lines.append("")

    lines.append("\u2501" * 30)
    lines.append(f"Total: {len(prereqs)} prerequisite edges, {len(related)} related edges")
    lines.append(f"New: {created_count} | Skipped (existing): {skipped_count}")
    lines.append("Status: Relationships extracted \u2705")

    return "\n".join(lines)


async def extract_concept_relationships(topic_name: str) -> str:
    """Extract and store concept relationships for a topic using LLM analysis.

    Fail Soft: all errors return error strings, never raise.
    """
    start = time.monotonic()
    normalized_name = topic_name.strip()
    if not normalized_name:
        return "Error: topic_name is empty. Hint: Provide the name of the topic."

    logger.info("extract_relationships start topic=%s", topic_name)

    try:
        async with async_session_factory() as session:
            # 1. Find Topic
            topic = await graph_service.get_topic_by_name(session, normalized_name)
            if topic is None:
                return (
                    f"Error: Topic '{topic_name}' not found. "
                    "Hint: Generate a learning plan first using generate_learning_plan."
                )

            # 2. Load Concepts
            concepts = await graph_service.get_concepts_by_topic(session, topic["id"])
            if len(concepts) < 2:
                return (
                    f"Error: Topic '{topic_name}' has fewer than 2 concepts. "
                    "Hint: A learning plan needs at least 2 concepts for relationship extraction."
                )

            logger.info(
                "extract_relationships concepts_loaded count=%d topic=%s",
                len(concepts), topic_name,
            )

            # 3. Build name→ID mapping
            name_to_id: dict[str, int] = {
                c["name"].strip().lower(): c["id"] for c in concepts
            }
            concept_ids = [c["id"] for c in concepts]

            # 4. Build prompt text (name + definition)
            concept_list_text = "\n".join(
                f"- {c['name']}" + (f": {c['definition']}" if c.get("definition") else "")
                for c in concepts
            )

            # 5. Call LLM (with timeout)
            try:
                result = await asyncio.wait_for(
                    get_chat_completion(
                        messages=[{
                            "role": "user",
                            "content": RELATIONSHIP_EXTRACTION_PROMPT.format(
                                concepts=concept_list_text
                            ),
                        }],
                        provider=get_providers()[0],
                        max_tokens=4000,
                    ),
                    timeout=_LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "extract_relationships failed stage=llm_timeout topic=%s",
                    topic_name,
                )
                return (
                    f"Error: LLM analysis timed out after {_LLM_TIMEOUT_SECONDS}s. "
                    "Hint: The concept list may be too large. Try again."
                )

            if isinstance(result, str) and result.startswith("Error"):
                logger.warning(
                    "extract_relationships failed stage=llm topic=%s error=%s",
                    topic_name, result,
                )
                return (
                    "Error: Failed to analyze concept relationships. "
                    "Hint: Try again \u2014 LLM output varies between calls."
                )

            # 6. Parse + validate JSON
            parsed = _parse_and_validate_relationships(result, name_to_id)
            if isinstance(parsed, str):
                if "Validation" in parsed:
                    # Extract detail from "Error: Validation — <detail>"
                    detail = parsed.split("\u2014", 1)[-1].strip() if "\u2014" in parsed else parsed
                    logger.warning(
                        "extract_relationships failed stage=validation topic=%s error=%s",
                        topic_name, parsed,
                    )
                    return (
                        f"Error: Extracted relationships are invalid ({detail}). "
                        "Hint: Try again \u2014 LLM output varies between calls."
                    )
                else:
                    logger.warning(
                        "extract_relationships failed stage=parse topic=%s error=%s",
                        topic_name, parsed,
                    )
                    return (
                        "Error: Could not parse relationships from LLM response. "
                        "Hint: Try again \u2014 LLM output varies between calls."
                    )

            logger.info("extract_relationships llm_result relationships=%d", len(parsed))

            if len(parsed) == 0:
                return (
                    f"No meaningful relationships identified between the "
                    f"{len(concepts)} concepts in '{topic_name}'. "
                    "This is normal for loosely structured content."
                )

            # 7. Pre-check existing edges (idempotency)
            existing_edges = await graph_service.get_edges_for_concepts(session, concept_ids)
            existing_set = {
                (e["source_concept_id"], e["target_concept_id"], e["relationship_type"])
                for e in existing_edges
            }

            # 8. Batch create new edges (auto_commit=False)
            try:
                created_count = 0
                skipped_count = 0
                for rel in parsed:
                    if (rel["source_id"], rel["target_id"], rel["type"]) in existing_set:
                        skipped_count += 1
                        continue
                    await graph_service.add_edge(
                        session,
                        rel["source_id"],
                        rel["target_id"],
                        rel["type"],
                        auto_commit=False,
                    )
                    created_count += 1
                await session.commit()
                await graph_service.load_graph(session)
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "extract_relationships failed stage=db topic=%s error=%s",
                    topic_name, exc,
                )
                return (
                    "Error: Failed to save relationships to database. "
                    "Hint: This is an internal error \u2014 please try again."
                )

        elapsed = time.monotonic() - start
        logger.info(
            "extract_relationships stored created=%d skipped=%d elapsed=%.1fs",
            created_count, skipped_count, elapsed,
        )
        return _format_relationships_output(topic_name, parsed, created_count, skipped_count)

    except Exception as exc:
        logger.warning(
            "extract_relationships failed stage=unexpected topic=%s error=%s",
            topic_name, exc,
        )
        return f"Error: Unexpected error extracting relationships \u2014 {exc}"
