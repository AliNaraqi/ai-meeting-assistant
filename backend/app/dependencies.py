"""Authentication helpers and FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import User
from app.services.demo import enforce_demo_writable

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    email: str


def create_access_token(
    *,
    user_id: UUID,
    email: str,
    settings: Settings,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "aud": settings.supabase_jwt_audience if settings.auth_mode == "supabase" else "dev",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
    }
    secret = _signing_secret(settings)
    return jwt.encode(payload, secret, algorithm="HS256")


def _signing_secret(settings: Settings) -> str:
    if settings.auth_mode == "supabase":
        if not settings.supabase_jwt_secret:
            raise RuntimeError("SUPABASE_JWT_SECRET is required when AUTH_MODE=supabase")
        return settings.supabase_jwt_secret
    return settings.secret_key


def decode_access_token(token: str, settings: Settings) -> AuthUser:
    secret = _signing_secret(settings)
    audience = settings.supabase_jwt_audience if settings.auth_mode == "supabase" else "dev"
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "Invalid or expired access token.",
                }
            },
        ) from exc

    try:
        user_id = UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "Token subject is invalid.",
                }
            },
        ) from exc

    email = str(payload.get("email") or "")
    return AuthUser(id=user_id, email=email)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "Missing bearer access token.",
                }
            },
        )

    auth_user = decode_access_token(credentials.credentials, settings)
    user = db.scalar(select(User).where(User.id == auth_user.id))
    if user is None:
        # Dev tokens may be issued before the row is visible; create lazily for supabase-mapped IDs.
        if not auth_user.email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": {
                        "code": "unauthorized",
                        "message": "Authenticated user is not provisioned.",
                    }
                },
            )
        user = User(
            id=auth_user.id,
            email=auth_user.email.lower(),
            audio_retention_days=settings.audio_retention_days,
        )
        db.add(user)
        db.flush()
    return user


def require_writable_user(
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """Like get_current_user, but rejects the shared demo account for writes."""
    enforce_demo_writable(current_user, settings)
    return current_user
