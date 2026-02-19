"""Unit tests for prompt_service — prompt loading, caching, and Fail Soft fallback.

Covers:
(a) Load prompt from file successfully
(b) Missing file → fallback to default prompt with warning
(c) Caching: second load returns cached content
(d) mentor_mode_enabled=False → neutral assistant prompt
(e) Cache invalidation on file change (mtime-based)
"""

from pathlib import Path
from unittest.mock import patch

import pytest


class TestLoadSystemPrompt:
    """Tests for prompt_service.load_system_prompt()."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear the prompt cache before each test."""
        from app.services.prompt_service import _prompt_cache
        _prompt_cache.clear()

    async def test_load_prompt_from_file(self, tmp_path: Path):
        """(a) Prompt file exists → returns file content."""
        from app.services.prompt_service import load_system_prompt

        prompt_file = tmp_path / "mentor_system_prompt.md"
        prompt_file.write_text("# Mentor Persona\nYou are a Socratic tutor.", encoding="utf-8")

        with patch("app.services.prompt_service.settings") as mock_settings:
            mock_settings.system_prompt_path = str(prompt_file)
            mock_settings.mentor_mode_enabled = True

            result = await load_system_prompt()

        assert "Socratic tutor" in result
        assert "# Mentor Persona" in result

    async def test_missing_file_returns_fallback(self, tmp_path: Path):
        """(b) Prompt file does not exist → returns safe default prompt + logs warning."""
        from app.services.prompt_service import load_system_prompt

        with patch("app.services.prompt_service.settings") as mock_settings:
            mock_settings.system_prompt_path = str(tmp_path / "nonexistent.md")
            mock_settings.mentor_mode_enabled = True

            result = await load_system_prompt()

        assert "assistant" in result.lower()

    async def test_cache_returns_same_content(self, tmp_path: Path):
        """(c) Second call returns cached content without re-reading file."""
        from app.services.prompt_service import load_system_prompt

        prompt_file = tmp_path / "mentor_system_prompt.md"
        prompt_file.write_text("Cached prompt content", encoding="utf-8")

        with patch("app.services.prompt_service.settings") as mock_settings:
            mock_settings.system_prompt_path = str(prompt_file)
            mock_settings.mentor_mode_enabled = True

            result1 = await load_system_prompt()
            result2 = await load_system_prompt()

        assert result1 == result2
        assert "Cached prompt content" in result1

    async def test_mentor_mode_disabled_returns_neutral_prompt(self, tmp_path: Path):
        """(d) mentor_mode_enabled=False → neutral assistant prompt, ignores file."""
        from app.services.prompt_service import load_system_prompt

        prompt_file = tmp_path / "mentor_system_prompt.md"
        prompt_file.write_text("# Mentor Persona\nYou are a Socratic tutor.", encoding="utf-8")

        with patch("app.services.prompt_service.settings") as mock_settings:
            mock_settings.system_prompt_path = str(prompt_file)
            mock_settings.mentor_mode_enabled = False

            result = await load_system_prompt()

        assert "Socratic" not in result
        assert "assistant" in result.lower()

    async def test_cache_invalidation_on_file_change(self, tmp_path: Path):
        """(e) File modification → cache invalidated, new content returned."""
        import os

        from app.services.prompt_service import load_system_prompt

        prompt_file = tmp_path / "mentor_system_prompt.md"
        prompt_file.write_text("Version 1", encoding="utf-8")

        with patch("app.services.prompt_service.settings") as mock_settings:
            mock_settings.system_prompt_path = str(prompt_file)
            mock_settings.mentor_mode_enabled = True

            result1 = await load_system_prompt()
            assert "Version 1" in result1

            # Modify file and update mtime
            prompt_file.write_text("Version 2", encoding="utf-8")
            stat = os.stat(prompt_file)
            os.utime(prompt_file, (stat.st_atime, stat.st_mtime + 1))

            result2 = await load_system_prompt()
            assert "Version 2" in result2
