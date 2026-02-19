"""Test that Alembic migrations actually create expected tables.

Uses alembic.command.upgrade to run real migrations against a fresh temp database,
NOT Base.metadata.create_all() — this proves the migration files themselves work.
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config

from alembic import command  # noqa: I001


def _run_migrations_on_fresh_db() -> dict[str, list[str]]:
    """Run alembic upgrade head on a fresh temp SQLite and return table→columns mapping."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    db_url = f"sqlite+aiosqlite:///{db_path}"

    with patch("app.config.settings") as mock_settings:
        mock_settings.database_url = db_url
        cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        command.upgrade(cfg, "head")

    conn = sqlite3.connect(db_path)
    query = "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
    tables_raw = conn.execute(query).fetchall()
    result: dict[str, list[str]] = {}
    for (table_name,) in tables_raw:
        cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()  # noqa: S608
        result[table_name] = [row[1] for row in cols]
    conn.close()
    Path(db_path).unlink(missing_ok=True)
    return result


def test_alembic_upgrade_creates_users_table():
    """alembic upgrade head must create users table from migration 001."""
    tables = _run_migrations_on_fresh_db()
    assert "users" in tables
    assert "id" in tables["users"]
    assert "name" in tables["users"]
    assert "current_context" in tables["users"]
    assert "skill_level" in tables["users"]


def test_alembic_upgrade_creates_sessions_table():
    """alembic upgrade head must create sessions table from migration 002."""
    tables = _run_migrations_on_fresh_db()
    assert "sessions" in tables
    assert "id" in tables["sessions"]
    assert "user_id" in tables["sessions"]
    assert "started_at" in tables["sessions"]
    assert "ended_at" in tables["sessions"]
    assert "summary" in tables["sessions"]
