"""Recording upload and playback routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import Response as RawResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_writable_user
from app.models import User
from app.schemas.recordings import (
    PlaybackUrlResponse,
    RecordingCompleteRequest,
    RecordingInitiateRequest,
    RecordingInitiateResponse,
    RecordingOut,
)
from app.services import recordings as recording_service
from app.services.storage import (
    create_playback_token,
    decode_playback_token,
    get_local_storage,
)

router = APIRouter(prefix="/api/v1/meetings", tags=["recordings"])


@router.post(
    "/{meeting_id}/recordings/initiate",
    response_model=RecordingInitiateResponse,
)
def initiate_recording_upload(
    meeting_id: UUID,
    payload: RecordingInitiateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RecordingInitiateResponse:
    return recording_service.initiate_upload(db, current_user, meeting_id, payload, settings)


@router.put("/{meeting_id}/recordings/upload", status_code=status.HTTP_204_NO_CONTENT)
async def upload_recording_bytes(
    meeting_id: UUID,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    upload_token: Annotated[str, Header(alias="X-Upload-Token")],
) -> Response:
    data = await request.body()
    recording_service.store_uploaded_bytes(
        meeting_id=meeting_id,
        upload_token=upload_token,
        data=data,
        settings=settings,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{meeting_id}/recordings/complete",
    response_model=RecordingOut,
    status_code=status.HTTP_201_CREATED,
)
def complete_recording_upload(
    meeting_id: UUID,
    payload: RecordingCompleteRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RecordingOut:
    recording = recording_service.complete_upload(db, current_user, meeting_id, payload, settings)
    return RecordingOut.model_validate(recording)


@router.get(
    "/{meeting_id}/recordings/{recording_id}/playback-url",
    response_model=PlaybackUrlResponse,
)
def get_playback_url(
    meeting_id: UUID,
    recording_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlaybackUrlResponse:
    _, recording = recording_service.get_owned_recording(db, current_user, meeting_id, recording_id)
    token = create_playback_token(
        meeting_id=meeting_id,
        recording_id=recording.id,
        storage_key=recording.storage_key,
        settings=settings,
    )
    url = (
        f"{settings.app_base_url.rstrip('/')}/api/v1/meetings/{meeting_id}"
        f"/recordings/{recording_id}/media?token={token}"
    )
    return PlaybackUrlResponse(url=url, expires_in_seconds=settings.signed_url_ttl_seconds)


@router.get("/{meeting_id}/recordings/{recording_id}/media")
def stream_recording_media(
    meeting_id: UUID,
    recording_id: UUID,
    token: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RawResponse:
    claims = decode_playback_token(token, settings)
    if str(claims.get("meeting_id")) != str(meeting_id):
        return RawResponse(status_code=status.HTTP_403_FORBIDDEN)
    if str(claims.get("recording_id")) != str(recording_id):
        return RawResponse(status_code=status.HTTP_403_FORBIDDEN)
    storage = get_local_storage(settings)
    data = storage.open_bytes(str(claims["storage_key"]))
    return RawResponse(content=data, media_type="application/octet-stream")


@router.delete(
    "/{meeting_id}/recordings/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_recording(
    meeting_id: UUID,
    recording_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    recording_service.delete_recording(db, current_user, meeting_id, recording_id, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
