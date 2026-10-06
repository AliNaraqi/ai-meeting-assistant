"""Schemas for share links, calendar import, and templates."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ShareCreateRequest(BaseModel):
    expires_in_hours: int = Field(default=72, ge=1, le=720)
    include_transcript: bool = True
    include_insights: bool = True


class ShareLinkOut(BaseModel):
    id: UUID
    token: str
    url: str | None = None
    expires_at: datetime
    revoked_at: datetime | None = None
    include_transcript: bool
    include_insights: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ShareCreateResponse(ShareLinkOut):
    url: str


class IcsImportRequest(BaseModel):
    ics_text: str = Field(min_length=20, max_length=200_000)
    consent_confirmed: bool = False
    meeting_type: str = "general"


class TemplateOut(BaseModel):
    id: str
    label: str
    description: str
    focus: list[str]
