"""Recording upload, complete, playback, and delete flows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Meeting, MeetingStatus, Recording, User
from app.schemas.recordings import (
    RecordingCompleteRequest,
    RecordingInitiateRequest,
    RecordingInitiateResponse,
)
from app.services import meetings as meeting_service
from app.services.storage import (
    create_upload_ticket,
    decode_upload_token,
    generate_storage_key,
    get_local_storage,
    sanitize_filename,
    validate_declared_media,
)


def initiate_upload(
    db: Session,
    owner: User,
    meeting_id: UUID,
    payload: RecordingInitiateRequest,
    settings: Settings,
) -> RecordingInitiateResponse:
    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    if meeting.consent_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "consent_required",
                    "message": "Confirm participant consent before uploading audio.",
                }
            },
        )
    if meeting.status not in {
        MeetingStatus.draft.value,
        MeetingStatus.uploading.value,
        MeetingStatus.failed.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "invalid_state",
                    "message": "This meeting cannot accept a new recording upload.",
                }
            },
        )

    filename = sanitize_filename(payload.original_filename)
    validate_declared_media(
        mime_type=payload.mime_type,
        size_bytes=payload.size_bytes,
        original_filename=filename,
        settings=settings,
    )
    storage_key = generate_storage_key(meeting.id, filename)
    ticket = create_upload_ticket(
        meeting_id=meeting.id,
        storage_key=storage_key,
        mime_type=payload.mime_type.lower().strip(),
        size_bytes=payload.size_bytes,
        source=payload.source,
        settings=settings,
    )
    meeting.status = MeetingStatus.uploading.value
    db.add(meeting)
    db.flush()
    return RecordingInitiateResponse(
        upload_token=ticket.upload_token,
        storage_key=ticket.storage_key,
        storage_bucket=ticket.storage_bucket,
        upload_url=ticket.upload_url,
        expires_at=ticket.expires_at,
    )


def store_uploaded_bytes(
    *,
    meeting_id: UUID,
    upload_token: str,
    data: bytes,
    settings: Settings,
) -> None:
    claims = decode_upload_token(upload_token, settings)
    if str(claims.get("meeting_id")) != str(meeting_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "forbidden",
                    "message": "Upload token does not match this meeting.",
                }
            },
        )
    expected_size = int(str(claims["size_bytes"]))
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "invalid_media", "message": "Uploaded body is empty."}},
        )
    if len(data) > expected_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": {
                    "code": "file_too_large",
                    "message": "Uploaded body exceeds the declared size.",
                }
            },
        )
    if settings.storage_backend != "local":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "error": {
                    "code": "storage_error",
                    "message": "Direct API upload is only enabled for local storage.",
                }
            },
        )
    storage = get_local_storage(settings)
    storage.save_bytes(str(claims["storage_key"]), data)


def complete_upload(
    db: Session,
    owner: User,
    meeting_id: UUID,
    payload: RecordingCompleteRequest,
    settings: Settings,
) -> Recording:
    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    claims = decode_upload_token(payload.upload_token, settings)
    if str(claims.get("meeting_id")) != str(meeting.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "forbidden",
                    "message": "Upload token does not match this meeting.",
                }
            },
        )
    if str(claims.get("storage_key")) != payload.storage_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "storage_error",
                    "message": "storage_key does not match the upload token.",
                }
            },
        )

    storage = get_local_storage(settings)
    stored = storage.inspect(payload.storage_key)
    if stored.size_bytes != payload.size_bytes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "storage_error",
                    "message": "Stored object size does not match the completion request.",
                }
            },
        )
    if payload.sha256 and stored.sha256 and payload.sha256 != stored.sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "storage_error",
                    "message": "Checksum mismatch for stored object.",
                }
            },
        )

    retention_days = owner.audio_retention_days or settings.audio_retention_days
    recording = Recording(
        meeting_id=meeting.id,
        storage_bucket=str(
            settings.supabase_storage_bucket
            if settings.storage_backend == "supabase"
            else "local-meeting-audio"
        ),
        storage_key=payload.storage_key,
        original_filename=None,
        mime_type=str(claims["mime_type"]),
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        source=str(claims["source"]),
        retention_until=datetime.now(UTC) + timedelta(days=retention_days),
    )
    meeting.status = MeetingStatus.uploaded.value
    meeting.duration_ms = meeting.duration_ms
    db.add(recording)
    db.add(meeting)
    db.flush()
    db.refresh(recording)
    return recording


def get_owned_recording(
    db: Session,
    owner: User,
    meeting_id: UUID,
    recording_id: UUID,
) -> tuple[Meeting, Recording]:
    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    recording = db.scalar(
        select(Recording).where(
            Recording.id == recording_id,
            Recording.meeting_id == meeting.id,
        )
    )
    if recording is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Recording not found."}},
        )
    return meeting, recording


def delete_recording(
    db: Session,
    owner: User,
    meeting_id: UUID,
    recording_id: UUID,
    settings: Settings,
) -> None:
    meeting, recording = get_owned_recording(db, owner, meeting_id, recording_id)
    if meeting.status not in {
        MeetingStatus.uploaded.value,
        MeetingStatus.uploading.value,
        MeetingStatus.draft.value,
        MeetingStatus.failed.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "invalid_state",
                    "message": "Processed recordings cannot be deleted from this endpoint.",
                }
            },
        )
    storage = get_local_storage(settings)
    storage.delete(recording.storage_key)
    db.delete(recording)
    if meeting.status in {MeetingStatus.uploaded.value, MeetingStatus.uploading.value}:
        remaining = db.scalar(
            select(Recording.id).where(Recording.meeting_id == meeting.id).limit(1)
        )
        if remaining is None:
            meeting.status = MeetingStatus.draft.value
            db.add(meeting)
    db.flush()
