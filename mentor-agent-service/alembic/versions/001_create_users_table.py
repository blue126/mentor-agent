"""create users table

Revision ID: 001
Revises:
Create Date: 2026-02-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("current_context", sa.Text(), nullable=True),
        sa.Column("skill_level", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("users")
