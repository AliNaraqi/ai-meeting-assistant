"""Create and manage processing jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Job, JobKind, JobStatus, MeetingStatus, Recording, User
from app.services import meetings as meeting_service
from app.services import quotas as quota_service
from app.services.pipeline import enqueue_or_run_job


def _active_job(db: Session, meeting_id: UUID) -> Job | None:
    return db.scalar(
        select(Job)
        .where(
            Job.meeting_id == meeting_id,
            Job.status.in_([JobStatus.queued.value, JobStatus.running.value]),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )


def start_full_process(
    db: Session,
    owner: User,
    meeting_id: UUID,
    settings: Settings,
) -> Job:
    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    if meeting.status not in {
        MeetingStatus.uploaded.value,
        MeetingStatus.failed.value,
        MeetingStatus.ready.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "invalid_state",
                    "message": "Meeting must be uploaded before processing.",
                }
            },
        )

    recording = db.scalar(
        select(Recording)
        .where(Recording.meeting_id == meeting.id)
        .order_by(Recording.created_at.desc())
        .limit(1)
    )
    if recording is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "invalid_state",
                    "message": "Upload a recording before processing.",
                }
            },
        )

    quota_service.enforce_audio_minutes_quota(db, owner, settings)

    existing = _active_job(db, meeting.id)
    if existing is not None:
        return existing

    attempt = 1
    prior = db.scalar(
        select(Job)
        .where(Job.meeting_id == meeting.id, Job.kind == JobKind.full_process.value)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if prior is not None:
        attempt = prior.attempt + 1

    idempotency_key = f"{meeting.id}:full_process:{recording.id}:a{attempt}"
    job = Job(
        meeting_id=meeting.id,
        kind=JobKind.full_process.value,
        status=JobStatus.queued.value,
        stage=None,
        progress_percent=0,
        attempt=attempt,
        max_attempts=settings.job_max_attempts,
        idempotency_key=idempotency_key,
    )
    meeting.status = MeetingStatus.queued.value
    db.add(job)
    db.add(meeting)
    db.flush()
    db.refresh(job)

    # Commit before enqueue so the worker/inline runner can load the row.
    db.commit()
    enqueue_or_run_job(job.id, settings)
    db.refresh(job)
    return job


def latest_job(db: Session, owner: User, meeting_id: UUID) -> Job | None:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    return db.scalar(
        select(Job).where(Job.meeting_id == meeting_id).order_by(Job.created_at.desc()).limit(1)
    )


def retry_job(
    db: Session,
    owner: User,
    meeting_id: UUID,
    job_id: UUID,
    settings: Settings,
) -> Job:
    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    job = db.scalar(select(Job).where(Job.id == job_id, Job.meeting_id == meeting.id))
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Job not found."}},
        )
    if job.status != JobStatus.failed.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "invalid_state",
                    "message": "Only failed jobs can be retried.",
                }
            },
        )
    if job.attempt >= job.max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "quota_exceeded",
                    "message": "Maximum retry attempts reached.",
                }
            },
        )
    return start_full_process(db, owner, meeting_id, settings)


def cancel_job(db: Session, owner: User, meeting_id: UUID, job_id: UUID) -> Job:
    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    job = db.scalar(select(Job).where(Job.id == job_id, Job.meeting_id == meeting.id))
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Job not found."}},
        )
    if job.status not in {JobStatus.queued.value, JobStatus.running.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "invalid_state",
                    "message": "Only queued or running jobs can be cancelled.",
                }
            },
        )
    job.status = JobStatus.cancelled.value
    job.finished_at = datetime.now(UTC)
    if meeting.status in {MeetingStatus.queued.value, MeetingStatus.processing.value}:
        meeting.status = MeetingStatus.uploaded.value
    db.add(job)
    db.add(meeting)
    db.flush()
    db.refresh(job)
    return job
