"""Shared demo-user helpers (read-only portfolio demo account)."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.config import Settings, get_settings
from app.models import User

DEMO_TITLE = "Try me — Aurora weekly sync"


def is_demo_user(user: User, settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return user.email.lower() == cfg.demo_user_email.lower()


def enforce_demo_writable(user: User, settings: Settings | None = None) -> None:
    """Block mutating operations for the shared demo account."""
    if is_demo_user(user, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "demo_read_only",
                    "message": (
                        "The shared demo account is read-only. "
                        "Sign in with your own email to create or edit meetings."
                    ),
                }
            },
        )
