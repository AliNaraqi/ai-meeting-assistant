"""Structured meeting-intelligence models (source of truth for extraction)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ConfidenceLabel = Literal["high", "medium", "low"]


class EvidenceRef(BaseModel):
    segment_id: UUID


class KeyPoint(BaseModel):
    text: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(min_length=1)
    confidence_label: ConfidenceLabel


class Decision(BaseModel):
    text: str = Field(min_length=1)
    made_by: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)
    confidence_label: ConfidenceLabel


class ActionItem(BaseModel):
    task: str = Field(min_length=1)
    owner: str | None = None
    due_date: date | None = None
    due_date_text: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)
    confidence_label: ConfidenceLabel


class Question(BaseModel):
    question: str = Field(min_length=1)
    status: Literal["answered", "open", "partially_answered"]
    answer: str | None = None
    owner: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class Risk(BaseModel):
    text: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "unknown"] = "unknown"
    mitigation: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class Topic(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1)
    start_segment_id: UUID
    end_segment_id: UUID


class FollowUpEmail(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)


class MeetingIntelligence(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    suggested_title: str = Field(min_length=1, max_length=200)
    one_sentence_summary: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    key_points: list[KeyPoint] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=20)
    follow_up_email: FollowUpEmail


class Citation(BaseModel):
    segment_id: UUID


class MeetingAnswer(BaseModel):
    answer: str
    answer_status: Literal["supported", "partially_supported", "not_found"]
    citations: list[Citation] = Field(default_factory=list)
