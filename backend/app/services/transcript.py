"""Transcript editing, search, and speaker rename."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Participant, TranscriptSegmentRow, User
from app.services import meetings as meeting_service


def get_segment(
    db: Session, owner: User, meeting_id: UUID, segment_id: UUID
) -> TranscriptSegmentRow:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    segment = db.scalar(
        select(TranscriptSegmentRow).where(
            TranscriptSegmentRow.id == segment_id,
            TranscriptSegmentRow.meeting_id == meeting_id,
        )
    )
    if segment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Transcript segment not found."}},
        )
    return segment


def patch_segment(
    db: Session,
    owner: User,
    meeting_id: UUID,
    segment_id: UUID,
    *,
    text: str | None,
    speaker_label: str | None,
) -> TranscriptSegmentRow:
    segment = get_segment(db, owner, meeting_id, segment_id)
    if text is not None:
        cleaned = text.strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "validation_error",
                        "message": "Segment text cannot be empty.",
                    }
                },
            )
        segment.text = cleaned
        segment.is_user_edited = True
    if speaker_label is not None:
        label = speaker_label.strip()
        if not label:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "validation_error",
                        "message": "Speaker label cannot be empty.",
                    }
                },
            )
        segment.speaker_label = label
        segment.is_user_edited = True
    db.add(segment)
    db.flush()
    db.refresh(segment)
    return segment


def rename_speaker(
    db: Session,
    owner: User,
    meeting_id: UUID,
    *,
    speaker_label: str,
    display_name: str,
) -> int:
    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    label = speaker_label.strip()
    name = display_name.strip()
    if not label or not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "validation_error",
                    "message": "speaker_label and display_name are required.",
                }
            },
        )

    participant = db.scalar(
        select(Participant).where(
            Participant.meeting_id == meeting.id,
            Participant.speaker_label == label,
        )
    )
    if participant is None:
        participant = Participant(
            id=uuid4(),
            meeting_id=meeting.id,
            display_name=name,
            speaker_label=label,
        )
    else:
        participant.display_name = name
    db.add(participant)
    db.flush()

    rows = list(
        db.scalars(
            select(TranscriptSegmentRow).where(
                TranscriptSegmentRow.meeting_id == meeting.id,
                TranscriptSegmentRow.speaker_label == label,
            )
        ).all()
    )
    for row in rows:
        row.participant_id = participant.id
        db.add(row)
    db.flush()
    return len(rows)


def search_transcript(
    db: Session,
    owner: User,
    meeting_id: UUID,
    *,
    query: str,
    limit: int = 50,
) -> list[TranscriptSegmentRow]:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    q = query.strip()
    if not q:
        return []
    pattern = f"%{q}%"
    return list(
        db.scalars(
            select(TranscriptSegmentRow)
            .where(
                TranscriptSegmentRow.meeting_id == meeting_id,
                or_(
                    TranscriptSegmentRow.text.ilike(pattern),
                    TranscriptSegmentRow.speaker_label.ilike(pattern),
                ),
            )
            .order_by(TranscriptSegmentRow.ordinal.asc())
            .limit(limit)
        ).all()
    )


def speaker_display_map(db: Session, meeting_id: UUID) -> dict[str, str]:
    rows = list(
        db.scalars(select(Participant).where(Participant.meeting_id == meeting_id)).all()
    )
    mapping: dict[str, str] = {}
    for row in rows:
        if row.speaker_label:
            mapping[row.speaker_label] = row.display_name
    return mapping
