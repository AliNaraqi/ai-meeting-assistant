"""Recording upload and playback schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

RecordingSource = Literal["browser", "upload"]


class RecordingInitiateRequest(BaseModel):
    original_filename: str | None = Field(default=None, max_length=255)
    mime_type: str = Field(min_length=3, max_length=120)
    size_bytes: int = Field(gt=0)
    source: RecordingSource = "upload"
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class RecordingInitiateResponse(BaseModel):
    upload_token: str
    storage_key: str
    storage_bucket: str
    upload_url: str
    expires_at: datetime


class RecordingCompleteRequest(BaseModel):
    upload_token: str
    storage_key: str
    size_bytes: int = Field(gt=0)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class RecordingOut(BaseModel):
    id: UUID
    mime_type: str
    size_bytes: int
    source: RecordingSource
    original_filename: str | None = None
    duration_ms: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PlaybackUrlResponse(BaseModel):
    url: str
    expires_in_seconds: int
