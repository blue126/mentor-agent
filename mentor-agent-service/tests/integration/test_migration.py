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


def test_alembic_upgrade_creates_topics_table():
    """alembic upgrade head must create topics table from migration 003."""
    tables = _run_migrations_on_fresh_db()
    assert "topics" in tables
    assert "id" in tables["topics"]
    assert "name" in tables["topics"]
    assert "description" in tables["topics"]
    assert "source_material" in tables["topics"]
    assert "created_at" in tables["topics"]


def test_alembic_upgrade_creates_concepts_table():
    """alembic upgrade head must create concepts table from migration 003."""
    tables = _run_migrations_on_fresh_db()
    assert "concepts" in tables
    assert "id" in tables["concepts"]
    assert "topic_id" in tables["concepts"]
    assert "name" in tables["concepts"]
    assert "definition" in tables["concepts"]
    assert "difficulty" in tables["concepts"]
    assert "created_at" in tables["concepts"]


def test_alembic_upgrade_creates_concept_edges_table():
    """alembic upgrade head must create concept_edges table from migration 003."""
    tables = _run_migrations_on_fresh_db()
    assert "concept_edges" in tables
    assert "id" in tables["concept_edges"]
    assert "source_concept_id" in tables["concept_edges"]
    assert "target_concept_id" in tables["concept_edges"]
    assert "relationship_type" in tables["concept_edges"]
    assert "weight" in tables["concept_edges"]
    assert "created_at" in tables["concept_edges"]
