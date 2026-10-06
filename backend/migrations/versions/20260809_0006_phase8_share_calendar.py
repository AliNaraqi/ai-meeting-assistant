"""Phase 8 share links and calendar metadata

Revision ID: 20260809_0006
Revises: 20260809_0005
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0006"
down_revision: str | None = "20260809_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("location", sa.String(length=500), nullable=True))
    op.add_column("meetings", sa.Column("calendar_event_uid", sa.String(length=255), nullable=True))
    op.add_column("meetings", sa.Column("calendar_provider", sa.String(length=64), nullable=True))

    op.create_table(
        "meeting_share_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("include_transcript", sa.Boolean(), nullable=False),
        sa.Column("include_insights", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_meeting_share_links_token", "meeting_share_links", ["token"], unique=True)
    op.create_index(
        op.f("ix_meeting_share_links_meeting_id"),
        "meeting_share_links",
        ["meeting_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_meeting_share_links_meeting_id"), table_name="meeting_share_links")
    op.drop_index("ix_meeting_share_links_token", table_name="meeting_share_links")
    op.drop_table("meeting_share_links")
    op.drop_column("meetings", "calendar_provider")
    op.drop_column("meetings", "calendar_event_uid")
    op.drop_column("meetings", "location")
