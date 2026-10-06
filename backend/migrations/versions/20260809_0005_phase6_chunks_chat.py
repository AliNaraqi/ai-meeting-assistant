"""Phase 6 transcript chunks and chat messages

Revision ID: 20260809_0005
Revises: 20260805_0004
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0005"
down_revision: str | None = "20260805_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcript_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("first_segment_id", sa.Uuid(), nullable=False),
        sa.Column("last_segment_id", sa.Uuid(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transcript_chunks_meeting", "transcript_chunks", ["meeting_id"])
    op.create_index(
        op.f("ix_transcript_chunks_meeting_id"), "transcript_chunks", ["meeting_id"], unique=False
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("answer_status", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_messages_meeting_created", "chat_messages", ["meeting_id", "created_at"]
    )
    op.create_index(op.f("ix_chat_messages_meeting_id"), "chat_messages", ["meeting_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_messages_meeting_id"), table_name="chat_messages")
    op.drop_index("ix_chat_messages_meeting_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(op.f("ix_transcript_chunks_meeting_id"), table_name="transcript_chunks")
    op.drop_index("ix_transcript_chunks_meeting", table_name="transcript_chunks")
    op.drop_table("transcript_chunks")
