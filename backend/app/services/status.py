"""Public ops status snapshot for reviewers and health checks."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from redis import Redis
from rq import Queue
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Job
from app.services.providers import openai_enabled

logger = logging.getLogger(__name__)


def _queue_length(settings: Settings) -> int | None:
    try:
        conn = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        queue = Queue("meeting-processing", connection=conn)
        return int(queue.count)
    except Exception:
        logger.debug("Could not read RQ queue length", exc_info=True)
        return None


def build_status_payload(db: Session, settings: Settings) -> dict[str, Any]:
    provider_mode = "openai" if openai_enabled() else "mock"
    last_job = db.scalar(select(Job).order_by(desc(Job.created_at)).limit(1))
    job_count = db.scalar(select(func.count()).select_from(Job)) or 0

    last_job_at: datetime | None = None
    last_job_status: str | None = None
    if last_job is not None:
        last_job_at = last_job.finished_at or last_job.started_at or last_job.created_at
        last_job_status = last_job.status

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "provider_mode": provider_mode,
        "openai_configured": openai_enabled(),
        "job_runner": settings.job_runner,
        "queue_name": "meeting-processing",
        "queue_length": _queue_length(settings),
        "jobs_total": int(job_count),
        "last_job_at": last_job_at.isoformat() if last_job_at else None,
        "last_job_status": last_job_status,
        "auth_mode": settings.auth_mode,
        "storage_backend": settings.storage_backend,
    }
