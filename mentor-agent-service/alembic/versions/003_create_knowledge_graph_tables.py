"""create knowledge graph tables

Revision ID: 003
Revises: 002
Create Date: 2026-02-21

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_material", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "concepts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "concept_edges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_concept_id", sa.Integer(), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("target_concept_id", sa.Integer(), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), server_default="1.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_concept_id", "target_concept_id", "relationship_type"),
    )


def downgrade() -> None:
    op.drop_table("concept_edges")
    op.drop_table("concepts")
    op.drop_table("topics")
