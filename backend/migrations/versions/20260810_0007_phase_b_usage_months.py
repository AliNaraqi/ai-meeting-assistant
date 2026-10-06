"""Phase B usage month counters

Revision ID: 20260810_0007
Revises: 20260809_0006
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0007"
down_revision: str | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_months",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("audio_ms", sa.BigInteger(), nullable=False),
        sa.Column("llm_tokens", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "period", name="uq_usage_months_user_period"),
    )
    op.create_index(op.f("ix_usage_months_user_id"), "usage_months", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_months_user_id"), table_name="usage_months")
    op.drop_table("usage_months")
