"""Current-user profile and usage endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.services import quotas as quota_service

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("/usage")
def get_my_usage(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Return monthly audio/LLM quota usage and remaining allowance."""
    return quota_service.usage_snapshot(db, current_user, settings)
