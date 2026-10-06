"""Retention cleanup for expired audio objects."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Recording
from app.services.storage import get_local_storage

logger = logging.getLogger(__name__)


def purge_expired_audio(db: Session, settings: Settings | None = None) -> dict[str, int]:
    """Delete storage objects and recording rows past retention_until."""
    cfg = settings or get_settings()
    now = datetime.now(UTC)
    expired = list(
        db.scalars(
            select(Recording).where(
                Recording.retention_until.is_not(None),
                Recording.retention_until < now,
            )
        ).all()
    )
    storage = get_local_storage(cfg)
    deleted_files = 0
    deleted_rows = 0
    for recording in expired:
        try:
            storage.delete(recording.storage_key)
            deleted_files += 1
        except Exception:
            logger.warning(
                "Failed to delete storage key for recording %s",
                recording.id,
                exc_info=True,
            )
        db.delete(recording)
        deleted_rows += 1
    if deleted_rows:
        db.flush()
    return {
        "expired_recordings": len(expired),
        "deleted_files": deleted_files,
        "deleted_rows": deleted_rows,
    }
