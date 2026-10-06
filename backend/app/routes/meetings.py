"""Meeting CRUD routes with owner isolation."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_writable_user
from app.models import Meeting, MeetingStatus, MeetingType, User
from app.schemas.meetings import (
    MeetingCreate,
    MeetingDetail,
    MeetingListResponse,
    MeetingSummary,
    MeetingUpdate,
    SortOption,
)
from app.services import meetings as meeting_service
from app.services import quotas as quota_service

router = APIRouter(prefix="/api/v1/meetings", tags=["meetings"])


def _to_detail(meeting: Meeting) -> MeetingDetail:
    return meeting_service.meeting_to_detail(meeting)


@router.post("", response_model=MeetingDetail, status_code=status.HTTP_201_CREATED)
def create_meeting(
    payload: MeetingCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeetingDetail:

    quota_service.enforce_meeting_quota(db, current_user, settings)
    meeting = meeting_service.create_meeting(db, current_user, payload)
    return _to_detail(meeting)


@router.get("", response_model=MeetingListResponse)
def list_meetings(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    status_filter: Annotated[MeetingStatus | None, Query(alias="status")] = None,
    meeting_type: MeetingType | None = None,
    q: str | None = None,
    sort: SortOption = "created_at_desc",
    occurred_from: Annotated[datetime | None, Query(alias="from")] = None,
    occurred_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> MeetingListResponse:
    rows, next_cursor = meeting_service.list_owned_meetings(
        db,
        current_user,
        limit=limit,
        cursor=cursor,
        status_filter=status_filter,
        meeting_type=meeting_type.value if meeting_type else None,
        q=q,
        sort=sort,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    return MeetingListResponse(
        items=[
            MeetingSummary(
                id=row.id,
                title=row.title,
                status=MeetingStatus(row.status),
                meeting_type=MeetingType(row.meeting_type),
                created_at=row.created_at,
                occurred_at=row.occurred_at,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )


@router.get("/{meeting_id}", response_model=MeetingDetail)
def get_meeting(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MeetingDetail:
    meeting = meeting_service.get_owned_meeting(db, current_user, meeting_id)
    return _to_detail(meeting)


@router.patch("/{meeting_id}", response_model=MeetingDetail)
def patch_meeting(
    meeting_id: UUID,
    payload: MeetingUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
) -> MeetingDetail:
    meeting = meeting_service.get_owned_meeting(db, current_user, meeting_id)
    updated = meeting_service.update_meeting(db, meeting, payload)
    return _to_detail(updated)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_meeting(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    meeting = meeting_service.get_owned_meeting(db, current_user, meeting_id)
    meeting_service.delete_meeting(db, meeting, settings=settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
