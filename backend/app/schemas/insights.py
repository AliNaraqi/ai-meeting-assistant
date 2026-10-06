"""API schemas for insights and action items."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import ActionItemStatus, ActionPriority


class InsightOut(BaseModel):
    id: UUID
    version: int
    schema_version: str
    model_name: str
    prompt_version: str
    one_sentence_summary: str
    executive_summary: str
    key_points: list[Any]
    decisions: list[Any]
    questions: list[Any]
    risks: list[Any]
    topics: list[Any]
    follow_up_email: dict[str, Any]
    tags: list[Any]
    generated_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InsightUpdate(BaseModel):
    one_sentence_summary: str | None = Field(default=None, min_length=1)
    executive_summary: str | None = Field(default=None, min_length=1)


class InsightRegenerateRequest(BaseModel):
    sections: list[str] = Field(default_factory=list)
    use_edited_transcript: bool = True
    template: str | None = None


class ActionOut(BaseModel):
    id: UUID
    task: str
    owner_text: str | None = None
    due_date: date | None = None
    due_date_text: str | None = None
    priority: ActionPriority
    status: ActionItemStatus
    evidence_segment_ids: list[str]
    confidence_label: str
    is_user_edited: bool
    source_insight_version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActionUpdate(BaseModel):
    task: str | None = Field(default=None, min_length=1)
    owner_text: str | None = None
    due_date: date | None = None
    due_date_text: str | None = None
    priority: ActionPriority | None = None
    status: ActionItemStatus | None = None
