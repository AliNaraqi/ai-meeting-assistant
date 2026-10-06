"""Shareable meeting links (expiring, revocable)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.models import (
    ActionItemRow,
    Meeting,
    MeetingInsight,
    MeetingShareLink,
    MeetingStatus,
    TranscriptSegmentRow,
    User,
)
from app.services import meetings as meeting_service


def create_share_link(
    db: Session,
    owner: User,
    meeting_id: UUID,
    *,
    expires_in_hours: int = 72,
    include_transcript: bool = True,
    include_insights: bool = True,
    settings: Settings | None = None,
) -> tuple[MeetingShareLink, str]:
    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    if meeting.status != MeetingStatus.ready.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "invalid_state",
                    "message": "Only ready meetings can be shared.",
                }
            },
        )
    hours = max(1, min(expires_in_hours, 24 * 30))
    token = secrets.token_urlsafe(24)
    link = MeetingShareLink(
        id=uuid4(),
        meeting_id=meeting.id,
        created_by=owner.id,
        token=token,
        expires_at=datetime.now(UTC) + timedelta(hours=hours),
        include_transcript=include_transcript,
        include_insights=include_insights,
    )
    db.add(link)
    db.flush()
    db.refresh(link)
    cfg = settings or get_settings()
    url = f"{cfg.app_base_url.rstrip('/')}/share/{token}"
    return link, url


def revoke_share_link(
    db: Session, owner: User, meeting_id: UUID, link_id: UUID
) -> MeetingShareLink:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    link = db.scalar(
        select(MeetingShareLink).where(
            MeetingShareLink.id == link_id,
            MeetingShareLink.meeting_id == meeting_id,
        )
    )
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Share link not found."}},
        )
    link.revoked_at = datetime.now(UTC)
    db.add(link)
    db.flush()
    db.refresh(link)
    return link


def list_share_links(db: Session, owner: User, meeting_id: UUID) -> list[MeetingShareLink]:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    return list(
        db.scalars(
            select(MeetingShareLink)
            .where(MeetingShareLink.meeting_id == meeting_id)
            .order_by(MeetingShareLink.created_at.desc())
        ).all()
    )


def resolve_share_token(db: Session, token: str) -> MeetingShareLink:
    link = db.scalar(select(MeetingShareLink).where(MeetingShareLink.token == token))
    if link is None or link.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Share link not found."}},
        )
    expires = link.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error": {"code": "expired", "message": "Share link has expired."}},
        )
    return link


def public_meeting_payload(db: Session, link: MeetingShareLink) -> dict[str, object]:
    meeting = db.scalar(
        select(Meeting)
        .options(selectinload(Meeting.participants))
        .where(Meeting.id == link.meeting_id, Meeting.deleted_at.is_(None))
    )
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Meeting not found."}},
        )

    payload: dict[str, object] = {
        "title": meeting.title,
        "meeting_type": meeting.meeting_type,
        "language": meeting.language,
        "occurred_at": meeting.occurred_at.isoformat() if meeting.occurred_at else None,
        "location": meeting.location,
        "status": meeting.status,
        "participants": [
            {"display_name": p.display_name, "role": p.role} for p in meeting.participants
        ],
        "expires_at": link.expires_at.isoformat(),
    }

    if link.include_insights:
        insight = db.scalar(
            select(MeetingInsight)
            .where(MeetingInsight.meeting_id == meeting.id)
            .order_by(MeetingInsight.version.desc())
            .limit(1)
        )
        actions = list(
            db.scalars(
                select(ActionItemRow)
                .where(ActionItemRow.meeting_id == meeting.id)
                .order_by(ActionItemRow.created_at.asc())
            ).all()
        )
        payload["insights"] = (
            None
            if insight is None
            else {
                "one_sentence_summary": insight.one_sentence_summary,
                "executive_summary": insight.executive_summary,
                "decisions": insight.decisions,
                "key_points": insight.key_points,
            }
        )
        payload["actions"] = [
            {
                "task": a.task,
                "owner_text": a.owner_text,
                "due_date_text": a.due_date_text,
                "status": a.status,
            }
            for a in actions
        ]

    if link.include_transcript:
        segments = list(
            db.scalars(
                select(TranscriptSegmentRow)
                .where(TranscriptSegmentRow.meeting_id == meeting.id)
                .order_by(TranscriptSegmentRow.ordinal.asc())
                .limit(500)
            ).all()
        )
        payload["transcript"] = [
            {
                "speaker_label": s.speaker_label,
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "text": s.text,
            }
            for s in segments
        ]

    return payload
