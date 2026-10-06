"""Share links, calendar import, and template catalog routes."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_writable_user
from app.models import MeetingType, User
from app.schemas.integrations import (
    IcsImportRequest,
    ShareCreateRequest,
    ShareCreateResponse,
    ShareLinkOut,
    TemplateOut,
)
from app.schemas.meetings import MeetingCreate, MeetingDetail
from app.services import calendar_import as calendar_service
from app.services import meetings as meeting_service
from app.services import quotas as quota_service
from app.services import sharing as sharing_service
from app.services import templates as template_service

router = APIRouter(tags=["integrations"])


@router.get("/api/v1/templates", response_model=list[TemplateOut])
def get_templates() -> list[TemplateOut]:
    return [TemplateOut.model_validate(item) for item in template_service.list_templates()]


@router.post(
    "/api/v1/meetings/from-ics",
    response_model=MeetingDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_meeting_from_ics(
    payload: IcsImportRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeetingDetail:
    quota_service.enforce_meeting_quota(db, current_user, settings)
    parsed = calendar_service.parse_ics_event(payload.ics_text)
    try:
        typed = MeetingType(payload.meeting_type)
    except ValueError:
        typed = MeetingType.general
    created = meeting_service.create_meeting(
        db,
        current_user,
        MeetingCreate(
            title=parsed["title"],
            description=parsed.get("description"),
            meeting_type=typed,
            occurred_at=parsed.get("occurred_at"),
            location=parsed.get("location"),
            calendar_event_uid=parsed.get("calendar_event_uid"),
            calendar_provider=parsed.get("calendar_provider"),
            consent_confirmed=payload.consent_confirmed,
        ),
    )
    return meeting_service.meeting_to_detail(created)


@router.post(
    "/api/v1/meetings/{meeting_id}/share-links",
    response_model=ShareCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_share_link(
    meeting_id: UUID,
    payload: ShareCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ShareCreateResponse:
    link, url = sharing_service.create_share_link(
        db,
        current_user,
        meeting_id,
        expires_in_hours=payload.expires_in_hours,
        include_transcript=payload.include_transcript,
        include_insights=payload.include_insights,
        settings=settings,
    )
    return ShareCreateResponse(
        id=link.id,
        token=link.token,
        url=url,
        expires_at=link.expires_at,
        revoked_at=link.revoked_at,
        include_transcript=link.include_transcript,
        include_insights=link.include_insights,
        created_at=link.created_at,
    )


@router.get("/api/v1/meetings/{meeting_id}/share-links", response_model=list[ShareLinkOut])
def list_share_links(
    meeting_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[ShareLinkOut]:
    links = sharing_service.list_share_links(db, current_user, meeting_id)
    base = settings.app_base_url.rstrip("/")
    return [
        ShareLinkOut(
            id=link.id,
            token=link.token,
            url=f"{base}/share/{link.token}",
            expires_at=link.expires_at,
            revoked_at=link.revoked_at,
            include_transcript=link.include_transcript,
            include_insights=link.include_insights,
            created_at=link.created_at,
        )
        for link in links
    ]


@router.delete(
    "/api/v1/meetings/{meeting_id}/share-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_share_link(
    meeting_id: UUID,
    link_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_writable_user)],
) -> Response:
    sharing_service.revoke_share_link(db, current_user, meeting_id, link_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/v1/share/{token}")
def get_shared_meeting(
    token: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    link = sharing_service.resolve_share_token(db, token)
    return sharing_service.public_meeting_payload(db, link)
