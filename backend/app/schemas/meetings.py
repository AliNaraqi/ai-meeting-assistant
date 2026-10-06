"""Auth and meeting request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.entities import MeetingStatus, MeetingType


class DevLoginRequest(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    email: EmailStr


class DemoLoginResponse(TokenResponse):
    meeting_id: UUID
    read_only: bool = True


class ParticipantCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    role: str | None = Field(default=None, max_length=120)


class ParticipantOut(BaseModel):
    id: UUID
    display_name: str
    email: str | None = None
    role: str | None = None
    speaker_label: str | None = None

    model_config = {"from_attributes": True}


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    meeting_type: MeetingType = MeetingType.general
    language: str | None = Field(default=None, max_length=32)
    occurred_at: datetime | None = None
    location: str | None = Field(default=None, max_length=500)
    calendar_event_uid: str | None = Field(default=None, max_length=255)
    calendar_provider: str | None = Field(default=None, max_length=64)
    consent_confirmed: bool = False
    participants: list[ParticipantCreate] = Field(default_factory=list)


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    meeting_type: MeetingType | None = None
    language: str | None = Field(default=None, max_length=32)
    occurred_at: datetime | None = None
    location: str | None = Field(default=None, max_length=500)
    calendar_event_uid: str | None = Field(default=None, max_length=255)
    calendar_provider: str | None = Field(default=None, max_length=64)
    consent_confirmed: bool | None = None


class MeetingSummary(BaseModel):
    id: UUID
    title: str
    status: MeetingStatus
    meeting_type: MeetingType
    created_at: datetime
    occurred_at: datetime | None = None

    model_config = {"from_attributes": True}


class MeetingDetail(MeetingSummary):
    description: str | None = None
    language: str | None = None
    duration_ms: int | None = None
    location: str | None = None
    calendar_event_uid: str | None = None
    calendar_provider: str | None = None
    consent_confirmed_at: datetime | None = None
    summary_version: int
    updated_at: datetime
    participants: list[ParticipantOut] = Field(default_factory=list)


class MeetingListResponse(BaseModel):
    items: list[MeetingSummary]
    next_cursor: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


SortOption = Literal["created_at_desc", "created_at_asc", "title_asc"]
