"""Meeting Q&A and chat history routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas.qa import AnswerResponse, ChatHistoryResponse, QuestionRequest
from app.services import qa as qa_service
from app.services import quotas as quota_service

router = APIRouter(prefix="/api/v1/meetings", tags=["qa"])


@router.post("/{meeting_id}/questions", response_model=AnswerResponse)
def ask_meeting_question(
    meeting_id: UUID,
    payload: QuestionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnswerResponse:
    quota_service.enforce_question_quota(db, current_user, settings)
    return qa_service.ask_question(db, current_user, meeting_id, payload.question)


@router.get("/{meeting_id}/chat", response_model=ChatHistoryResponse)
def get_meeting_chat(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ChatHistoryResponse:
    items = qa_service.list_chat(db, current_user, meeting_id, limit=limit)
    return ChatHistoryResponse(items=items)
