"""Job and transcript API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import JobStatus


class JobOut(BaseModel):
    id: UUID
    status: JobStatus
    stage: str | None = None
    progress_percent: int
    attempt: int
    safe_error: dict[str, str] | None = None
    updated_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TranscriptSegmentOut(BaseModel):
    id: UUID
    ordinal: int
    speaker: dict[str, str | None]
    start_ms: int
    end_ms: int
    text: str
    is_user_edited: bool


class TranscriptResponse(BaseModel):
    items: list[TranscriptSegmentOut]
    next_cursor: int | None = None


class SegmentUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    speaker_label: str | None = Field(default=None, min_length=1)


class SpeakerRenameRequest(BaseModel):
    speaker_label: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)


class SpeakerRenameResponse(BaseModel):
    updated_segments: int


class ProcessRequest(BaseModel):
    force: bool = Field(default=False)


class ExportRequest(BaseModel):
    format: str = Field(default="markdown")
    include_transcript: bool = True
    include_participant_emails: bool = False
    include_audio_link: bool = False


class ExportResponse(BaseModel):
    id: str
    format: str
    status: str
    filename: str
    content: str
    content_type: str
