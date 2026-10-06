"""Transcript and meeting metadata schemas used by ML providers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class MeetingMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    meeting_type: Literal["general", "standup", "interview", "sales", "research", "lecture"] = (
        "general"
    )
    language: str | None = "en"
    occurred_at: datetime | None = None
    participant_aliases: list[str] = Field(default_factory=list)
    description: str | None = None


class TranscriptSegment(BaseModel):
    id: UUID
    ordinal: int = Field(ge=0)
    speaker_label: str
    speaker_display_name: str | None = None
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str
    language: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def end_after_start(self) -> TranscriptSegment:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self


class NormalizedTranscript(BaseModel):
    segments: list[TranscriptSegment]
    language: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    model_name: str
    provider: str = "mock"
