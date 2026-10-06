"""Q&A request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class CitationOut(BaseModel):
    segment_id: UUID
    start_ms: int
    speaker_name: str | None = None
    text: str | None = None


class AnswerResponse(BaseModel):
    answer: str
    answer_status: Literal["supported", "partially_supported", "not_found"]
    citations: list[CitationOut]
    model_name: str | None = None


class ChatMessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationOut] = Field(default_factory=list)
    answer_status: str | None = None
    model_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatHistoryResponse(BaseModel):
    items: list[ChatMessageOut]
