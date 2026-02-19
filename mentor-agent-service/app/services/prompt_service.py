"""Prompt service — loads and caches the system prompt with Fail Soft fallback.

Reads the mentor persona prompt from an external markdown file.
Supports mtime-based cache invalidation and graceful fallback on errors.
"""

import asyncio
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = "You are a helpful assistant."

# Cache: {path: (mtime, content)}
_prompt_cache: dict[str, tuple[float, str]] = {}


async def load_system_prompt() -> str:
    """Load the system prompt based on configuration.

    Returns the mentor persona prompt when mentor_mode_enabled is True,
    or a neutral assistant prompt when False.
    Falls back to DEFAULT_PROMPT if the file is missing or unreadable.
    """
    if not settings.mentor_mode_enabled:
        return DEFAULT_PROMPT

    prompt_path = settings.system_prompt_path
    resolved = Path(prompt_path)

    # Check if file exists
    if not resolved.is_file():
        logger.warning(
            "System prompt file not found: %s — using default prompt. "
            "Hint: create the file or update SYSTEM_PROMPT_PATH",
            prompt_path,
        )
        return DEFAULT_PROMPT

    # Check cache with mtime-based invalidation
    try:
        stat_result = await asyncio.to_thread(resolved.stat)
        current_mtime = stat_result.st_mtime
    except OSError as exc:
        logger.warning("Cannot stat prompt file %s: %s — using default prompt", prompt_path, exc)
        return DEFAULT_PROMPT

    cached = _prompt_cache.get(prompt_path)
    if cached is not None:
        cached_mtime, cached_content = cached
        if cached_mtime == current_mtime:
            return cached_content

    # Read file
    try:
        content = await asyncio.to_thread(resolved.read_text, encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read prompt file %s: %s — using default prompt", prompt_path, exc)
        return DEFAULT_PROMPT

    # Update cache
    _prompt_cache[prompt_path] = (current_mtime, content)
    return content
