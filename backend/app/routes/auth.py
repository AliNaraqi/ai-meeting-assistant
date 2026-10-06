"""Authentication routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.dependencies import create_access_token
from app.models import User
from app.schemas.meetings import DemoLoginResponse, DevLoginRequest, TokenResponse
from app.scripts.seed_demo import seed_demo

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/dev-login", response_model=TokenResponse)
def dev_login(
    payload: DevLoginRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    if settings.auth_mode != "dev":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "not_found",
                    "message": "Dev login is disabled outside AUTH_MODE=dev.",
                }
            },
        )

    email = str(payload.email).lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            display_name=payload.display_name,
            audio_retention_days=settings.audio_retention_days,
        )
        db.add(user)
        db.flush()
        db.refresh(user)
    elif payload.display_name and user.display_name != payload.display_name:
        user.display_name = payload.display_name
        db.add(user)
        db.flush()

    token = create_access_token(user_id=user.id, email=user.email, settings=settings)
    return TokenResponse(access_token=token, user_id=user.id, email=user.email)


@router.post("/demo-login", response_model=DemoLoginResponse)
def demo_login(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DemoLoginResponse:
    """Sign in as the shared read-only demo user and open the Try-me meeting."""
    if settings.auth_mode != "dev":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "not_found",
                    "message": "Demo login is available in AUTH_MODE=dev only.",
                }
            },
        )

    try:
        meeting_id = seed_demo(force=False, reset=False)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "demo_unavailable",
                    "message": "Could not prepare the demo meeting. Try again shortly.",
                }
            },
        ) from exc

    email = settings.demo_user_email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        # Seed committed in its own session; re-query after a short path.
        user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "demo_unavailable",
                    "message": "Demo user is not available.",
                }
            },
        )

    token = create_access_token(user_id=user.id, email=user.email, settings=settings)
    return DemoLoginResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        meeting_id=UUID(meeting_id),
        read_only=True,
    )
