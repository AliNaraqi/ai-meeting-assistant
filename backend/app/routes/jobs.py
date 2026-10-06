"""Processing job and transcript routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_writable_user
from app.models import Job, JobStatus, Recording, TranscriptSegmentRow, User
from app.schemas.jobs import (
    ExportRequest,
    ExportResponse,
    JobOut,
    SegmentUpdate,
    SpeakerRenameRequest,
    SpeakerRenameResponse,
    TranscriptResponse,
    TranscriptSegmentOut,
)
from app.schemas.recordings import RecordingOut
from app.services import export as export_service
from app.services import jobs as job_service
from app.services import meetings as meeting_service
from app.services import transcript as transcript_service

router = APIRouter(prefix="/api/v1/meetings", tags=["processing"])


def _job_out(job: Job) -> JobOut:
    safe_error = None
    if job.safe_error_code:
        safe_error = {
            "code": job.safe_error_code,
            "message": job.safe_error_message or "Processing failed.",
        }
    return JobOut(
        id=job.id,
        status=JobStatus(job.status),
        stage=job.stage,
        progress_percent=job.progress_percent,
        attempt=job.attempt,
        safe_error=safe_error,
        updated_at=job.finished_at or job.started_at or job.created_at,
        created_at=job.created_at,
    )


def _segment_out(row: TranscriptSegmentRow, displays: dict[str, str]) -> TranscriptSegmentOut:
    return TranscriptSegmentOut(
        id=row.id,
        ordinal=row.ordinal,
        speaker={
            "label": row.speaker_label,
            "participant_id": str(row.participant_id) if row.participant_id else None,
            "display_name": displays.get(row.speaker_label),
        },
        start_ms=row.start_ms,
        end_ms=row.end_ms,
        text=row.text,
        is_user_edited=row.is_user_edited,
    )


@router.post("/{meeting_id}/process", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def process_meeting(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobOut:
    job = job_service.start_full_process(db, current_user, meeting_id, settings)
    return _job_out(job)


@router.get("/{meeting_id}/jobs/latest", response_model=JobOut)
def get_latest_job(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JobOut:
    job = job_service.latest_job(db, current_user, meeting_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "No jobs found for this meeting."}},
        )
    return _job_out(job)


@router.post("/{meeting_id}/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(
    meeting_id: UUID,
    job_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobOut:
    job = job_service.retry_job(db, current_user, meeting_id, job_id, settings)
    return _job_out(job)


@router.post("/{meeting_id}/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    meeting_id: UUID,
    job_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
) -> JobOut:
    job = job_service.cancel_job(db, current_user, meeting_id, job_id)
    return _job_out(job)


@router.get("/{meeting_id}/transcript", response_model=TranscriptResponse)
def get_transcript(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> TranscriptResponse:
    meeting_service.get_owned_meeting(db, current_user, meeting_id)
    displays = transcript_service.speaker_display_map(db, meeting_id)
    rows = list(
        db.scalars(
            select(TranscriptSegmentRow)
            .where(
                TranscriptSegmentRow.meeting_id == meeting_id,
                TranscriptSegmentRow.ordinal >= cursor,
            )
            .order_by(TranscriptSegmentRow.ordinal.asc())
            .limit(limit + 1)
        ).all()
    )
    next_cursor = None
    if len(rows) > limit:
        next_cursor = rows[limit].ordinal
        rows = rows[:limit]
    return TranscriptResponse(
        items=[_segment_out(row, displays) for row in rows],
        next_cursor=next_cursor,
    )


@router.get("/{meeting_id}/transcript/search", response_model=TranscriptResponse)
def search_transcript(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TranscriptResponse:
    displays = transcript_service.speaker_display_map(db, meeting_id)
    rows = transcript_service.search_transcript(
        db, current_user, meeting_id, query=q, limit=limit
    )
    return TranscriptResponse(items=[_segment_out(row, displays) for row in rows], next_cursor=None)


@router.patch(
    "/{meeting_id}/transcript/segments/{segment_id}",
    response_model=TranscriptSegmentOut,
)
def patch_segment(
    meeting_id: UUID,
    segment_id: UUID,
    payload: SegmentUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
) -> TranscriptSegmentOut:
    row = transcript_service.patch_segment(
        db,
        current_user,
        meeting_id,
        segment_id,
        text=payload.text,
        speaker_label=payload.speaker_label,
    )
    displays = transcript_service.speaker_display_map(db, meeting_id)
    return _segment_out(row, displays)


@router.post("/{meeting_id}/speakers/rename", response_model=SpeakerRenameResponse)
def rename_speaker(
    meeting_id: UUID,
    payload: SpeakerRenameRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
) -> SpeakerRenameResponse:
    updated = transcript_service.rename_speaker(
        db,
        current_user,
        meeting_id,
        speaker_label=payload.speaker_label,
        display_name=payload.display_name,
    )
    return SpeakerRenameResponse(updated_segments=updated)


@router.get("/{meeting_id}/recordings", response_model=list[RecordingOut])
def list_recordings(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[RecordingOut]:
    meeting_service.get_owned_meeting(db, current_user, meeting_id)
    rows = list(
        db.scalars(
            select(Recording)
            .where(Recording.meeting_id == meeting_id)
            .order_by(Recording.created_at.desc())
        ).all()
    )
    return [RecordingOut.model_validate(row) for row in rows]


@router.post("/{meeting_id}/exports", response_model=ExportResponse)
def create_export(
    meeting_id: UUID,
    payload: ExportRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ExportResponse:
    fmt = payload.format.lower().strip()
    allowed = {"markdown", "json", "slack", "notion", "actions_csv"}
    if fmt not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "validation_error",
                    "message": "format must be markdown, json, slack, notion, or actions_csv.",
                }
            },
        )
    result = export_service.build_export(
        db,
        current_user,
        meeting_id,
        fmt=fmt,  # type: ignore[arg-type]
        include_transcript=payload.include_transcript,
        include_participant_emails=payload.include_participant_emails,
    )
    return ExportResponse.model_validate(result)
