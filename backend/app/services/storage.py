"""Private audio storage helpers (local filesystem for Phase 2)."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt
from fastapi import HTTPException, status

from app.config import Settings

ALLOWED_MIME_TYPES = {
    "audio/webm",
    "video/webm",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/mpga",
    "video/mp4",
}

ALLOWED_EXTENSIONS = {".webm", ".wav", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpga"}

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class UploadTicket:
    upload_token: str
    storage_key: str
    storage_bucket: str
    upload_url: str
    expires_at: datetime


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    size_bytes: int
    sha256: str | None


def sanitize_filename(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = _FILENAME_SAFE.sub("_", Path(name).name).strip("._")
    return cleaned[:200] or None


def validate_declared_media(
    *,
    mime_type: str,
    size_bytes: int,
    original_filename: str | None,
    settings: Settings,
) -> None:
    if size_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "invalid_media", "message": "File is empty."}},
        )
    if size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": {
                    "code": "file_too_large",
                    "message": "Uploaded file exceeds the configured size limit.",
                }
            },
        )
    normalized_mime = mime_type.lower().strip()
    if normalized_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error": {
                    "code": "unsupported_media",
                    "message": "MIME type is not supported.",
                }
            },
        )
    if original_filename:
        suffix = Path(original_filename).suffix.lower()
        if suffix and suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={
                    "error": {
                        "code": "unsupported_media",
                        "message": "File extension is not supported.",
                    }
                },
            )


def generate_storage_key(meeting_id: UUID, original_filename: str | None) -> str:
    suffix = Path(original_filename or "audio.webm").suffix.lower() or ".webm"
    if suffix not in ALLOWED_EXTENSIONS:
        suffix = ".webm"
    return f"meetings/{meeting_id}/{secrets.token_urlsafe(24)}{suffix}"


def create_upload_ticket(
    *,
    meeting_id: UUID,
    storage_key: str,
    mime_type: str,
    size_bytes: int,
    source: str,
    settings: Settings,
) -> UploadTicket:
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.signed_url_ttl_seconds)
    payload = {
        "typ": "upload",
        "meeting_id": str(meeting_id),
        "storage_key": storage_key,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "source": source,
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    bucket = (
        settings.supabase_storage_bucket
        if settings.storage_backend == "supabase"
        else "local-meeting-audio"
    )
    base = settings.app_base_url.rstrip("/")
    upload_url = f"{base}/api/v1/meetings/{meeting_id}/recordings/upload"
    return UploadTicket(
        upload_token=token,
        storage_key=storage_key,
        storage_bucket=bucket,
        upload_url=upload_url,
        expires_at=expires_at,
    )


def decode_upload_token(token: str, settings: Settings) -> dict[str, object]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "Upload token is invalid or expired.",
                }
            },
        ) from exc
    if payload.get("typ") != "upload":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "Upload token type is invalid.",
                }
            },
        )
    return payload


def create_playback_token(
    *,
    meeting_id: UUID,
    recording_id: UUID,
    storage_key: str,
    settings: Settings,
) -> str:
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.signed_url_ttl_seconds)
    payload = {
        "typ": "playback",
        "meeting_id": str(meeting_id),
        "recording_id": str(recording_id),
        "storage_key": storage_key,
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_playback_token(token: str, settings: Settings) -> dict[str, object]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "Playback URL is invalid or expired.",
                }
            },
        ) from exc
    if payload.get("typ") != "playback":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "Playback token type is invalid.",
                }
            },
        )
    return payload


class LocalAudioStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, storage_key: str) -> Path:
        target = (self.root / storage_key).resolve()
        if not str(target).startswith(str(self.root)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "storage_error",
                        "message": "Invalid storage key.",
                    }
                },
            )
        return target

    def save_bytes(self, storage_key: str, data: bytes) -> StoredObject:
        path = self.path_for(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        return StoredObject(storage_key=storage_key, size_bytes=len(data), sha256=digest)

    def inspect(self, storage_key: str) -> StoredObject:
        path = self.path_for(storage_key)
        if not path.is_file():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": {
                        "code": "storage_error",
                        "message": "Uploaded object was not found in storage.",
                    }
                },
            )
        data = path.read_bytes()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "invalid_media",
                        "message": "Stored object is empty.",
                    }
                },
            )
        return StoredObject(
            storage_key=storage_key,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def open_bytes(self, storage_key: str) -> bytes:
        return self.path_for(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        path = self.path_for(storage_key)
        if path.exists():
            path.unlink()


def get_local_storage(settings: Settings) -> LocalAudioStorage:
    return LocalAudioStorage(settings.local_storage_dir)
