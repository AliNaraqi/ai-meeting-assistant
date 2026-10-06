"""Meeting ownership queries and mutations."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, asc, desc, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Meeting, MeetingStatus, MeetingType, Participant, Recording, User
from app.schemas.meetings import (
    MeetingCreate,
    MeetingDetail,
    MeetingUpdate,
    ParticipantOut,
    SortOption,
)


def meeting_to_detail(meeting: Meeting) -> MeetingDetail:
    return MeetingDetail(
        id=meeting.id,
        title=meeting.title,
        status=MeetingStatus(meeting.status),
        meeting_type=MeetingType(meeting.meeting_type),
        created_at=meeting.created_at,
        occurred_at=meeting.occurred_at,
        description=meeting.description,
        language=meeting.language,
        duration_ms=meeting.duration_ms,
        location=meeting.location,
        calendar_event_uid=meeting.calendar_event_uid,
        calendar_provider=meeting.calendar_provider,
        consent_confirmed_at=meeting.consent_confirmed_at,
        summary_version=meeting.summary_version,
        updated_at=meeting.updated_at,
        participants=[ParticipantOut.model_validate(p) for p in meeting.participants],
    )


def _decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["created_at"]), UUID(payload["id"])
    except (ValueError, KeyError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "invalid_cursor",
                    "message": "The pagination cursor is invalid.",
                }
            },
        ) from exc


def encode_cursor(created_at: datetime, meeting_id: UUID) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(meeting_id)},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def create_meeting(db: Session, owner: User, payload: MeetingCreate) -> Meeting:
    now = datetime.now(UTC)
    meeting = Meeting(
        owner_id=owner.id,
        title=payload.title.strip(),
        description=payload.description,
        meeting_type=payload.meeting_type.value,
        language=payload.language,
        occurred_at=payload.occurred_at,
        location=payload.location,
        calendar_event_uid=payload.calendar_event_uid,
        calendar_provider=payload.calendar_provider,
        status=MeetingStatus.draft.value,
        consent_confirmed_at=now if payload.consent_confirmed else None,
    )
    for participant in payload.participants:
        meeting.participants.append(
            Participant(
                display_name=participant.display_name.strip(),
                email=str(participant.email) if participant.email else None,
                role=participant.role,
            )
        )
    db.add(meeting)
    db.flush()
    db.refresh(meeting)
    return meeting


def get_owned_meeting(db: Session, owner: User, meeting_id: UUID) -> Meeting:
    meeting = db.scalar(
        select(Meeting)
        .options(selectinload(Meeting.participants))
        .where(
            Meeting.id == meeting_id,
            Meeting.owner_id == owner.id,
            Meeting.deleted_at.is_(None),
        )
    )
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "not_found",
                    "message": "Meeting not found.",
                }
            },
        )
    return meeting


def list_owned_meetings(
    db: Session,
    owner: User,
    *,
    limit: int,
    cursor: str | None,
    status_filter: MeetingStatus | None,
    meeting_type: str | None,
    q: str | None,
    sort: SortOption,
    occurred_from: datetime | None,
    occurred_to: datetime | None,
) -> tuple[list[Meeting], str | None]:
    stmt: Select[tuple[Meeting]] = select(Meeting).where(
        Meeting.owner_id == owner.id,
        Meeting.deleted_at.is_(None),
    )
    if status_filter is not None:
        stmt = stmt.where(Meeting.status == status_filter.value)
    if meeting_type is not None:
        stmt = stmt.where(Meeting.meeting_type == meeting_type)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(Meeting.title.ilike(pattern), Meeting.description.ilike(pattern)))
    if occurred_from is not None:
        stmt = stmt.where(Meeting.occurred_at >= occurred_from)
    if occurred_to is not None:
        stmt = stmt.where(Meeting.occurred_at <= occurred_to)

    cursor_values = _decode_cursor(cursor)
    if sort == "created_at_asc":
        stmt = stmt.order_by(asc(Meeting.created_at), asc(Meeting.id))
        if cursor_values:
            created_at, meeting_id = cursor_values
            stmt = stmt.where(
                or_(
                    Meeting.created_at > created_at,
                    (Meeting.created_at == created_at) & (Meeting.id > meeting_id),
                )
            )
    elif sort == "title_asc":
        stmt = stmt.order_by(asc(Meeting.title), asc(Meeting.id))
    else:
        stmt = stmt.order_by(desc(Meeting.created_at), desc(Meeting.id))
        if cursor_values:
            created_at, meeting_id = cursor_values
            stmt = stmt.where(
                or_(
                    Meeting.created_at < created_at,
                    (Meeting.created_at == created_at) & (Meeting.id < meeting_id),
                )
            )

    rows = list(db.scalars(stmt.limit(limit + 1)).all())
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[:limit]
    return rows, next_cursor


def update_meeting(db: Session, meeting: Meeting, payload: MeetingUpdate) -> Meeting:
    data = payload.model_dump(exclude_unset=True)
    consent = data.pop("consent_confirmed", None)
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
    if "meeting_type" in data and data["meeting_type"] is not None:
        data["meeting_type"] = data["meeting_type"].value
    for key, value in data.items():
        setattr(meeting, key, value)
    if consent is True and meeting.consent_confirmed_at is None:
        meeting.consent_confirmed_at = datetime.now(UTC)
    db.add(meeting)
    db.flush()
    db.refresh(meeting)
    return meeting


def delete_meeting(db: Session, meeting: Meeting, *, settings: object | None = None) -> None:
    """Permanently delete a meeting and related storage objects."""
    from app.config import Settings, get_settings
    from app.models import MeetingShareLink, TranscriptChunk
    from app.services.storage import get_local_storage
    from sqlalchemy import delete as sa_delete

    cfg: Settings = settings if isinstance(settings, Settings) else get_settings()
    recordings = list(
        db.scalars(select(Recording).where(Recording.meeting_id == meeting.id)).all()
    )
    storage = get_local_storage(cfg)
    for recording in recordings:
        try:
            storage.delete(recording.storage_key)
        except Exception:
            pass

    # Explicit cleanup so delete-forever is observable even before CASCADE runs.
    db.execute(sa_delete(MeetingShareLink).where(MeetingShareLink.meeting_id == meeting.id))
    db.execute(sa_delete(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting.id))

    meeting.status = MeetingStatus.deleting.value
    meeting.deleted_at = datetime.now(UTC)
    db.delete(meeting)
    db.flush()
