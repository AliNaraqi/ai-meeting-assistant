"""Insights and action-item routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_writable_user
from app.models import User
from app.schemas.insights import (
    ActionOut,
    ActionUpdate,
    InsightOut,
    InsightRegenerateRequest,
    InsightUpdate,
)
from app.services import insights as insight_service

router = APIRouter(prefix="/api/v1/meetings", tags=["insights"])


@router.get("/{meeting_id}/insights", response_model=InsightOut)
def get_insights(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> InsightOut:
    insight = insight_service.get_active_insight(db, current_user, meeting_id)
    return InsightOut.model_validate(insight)


@router.patch("/{meeting_id}/insights", response_model=InsightOut)
def patch_insights(
    meeting_id: UUID,
    payload: InsightUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
) -> InsightOut:
    insight = insight_service.update_insight_summaries(
        db,
        current_user,
        meeting_id,
        one_sentence_summary=payload.one_sentence_summary,
        executive_summary=payload.executive_summary,
    )
    return InsightOut.model_validate(insight)


@router.post("/{meeting_id}/insights/regenerate", response_model=InsightOut)
def regenerate_insights(
    meeting_id: UUID,
    payload: InsightRegenerateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
) -> InsightOut:
    insight = insight_service.regenerate_insights(
        db,
        current_user,
        meeting_id,
        template=payload.template,
    )
    return InsightOut.model_validate(insight)


@router.get("/{meeting_id}/actions", response_model=list[ActionOut])
def list_actions(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ActionOut]:
    rows = insight_service.list_actions(db, current_user, meeting_id)
    return [ActionOut.model_validate(row) for row in rows]


@router.patch("/{meeting_id}/actions/{action_id}", response_model=ActionOut)
def patch_action(
    meeting_id: UUID,
    action_id: UUID,
    payload: ActionUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
) -> ActionOut:
    action = insight_service.get_owned_action(db, current_user, meeting_id, action_id)
    data = payload.model_dump(exclude_unset=True)
    if "priority" in data and data["priority"] is not None:
        data["priority"] = data["priority"].value
    if "status" in data and data["status"] is not None:
        data["status"] = data["status"].value
    from app.config import get_settings
    from app.services.redaction import redact_text

    settings = get_settings()
    if settings.redact_pii and "task" in data and isinstance(data["task"], str):
        data["task"] = redact_text(data["task"])
    for key, value in data.items():
        setattr(action, key, value)
    action.is_user_edited = True
    db.add(action)
    db.flush()
    db.refresh(action)
    return ActionOut.model_validate(action)


@router.delete(
    "/{meeting_id}/actions/{action_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_action(
    meeting_id: UUID,
    action_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
) -> Response:
    action = insight_service.get_owned_action(db, current_user, meeting_id, action_id)
    db.delete(action)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
