"""Meeting processing pipeline: validate → preprocess → transcribe → finalize."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.models import (
    Job,
    JobStage,
    JobStatus,
    Meeting,
    MeetingStatus,
    Recording,
    TranscriptSegmentRow,
    User,
)
from app.services import quotas as quota_service
from app.services.audio import AudioProcessingError, normalize_audio
from app.services.indexing import index_meeting
from app.services.insights import extract_and_store
from app.services.meeting_intelligence import MeetingIntelligenceError
from app.services.providers import get_transcription_provider
from app.services.quotas import QuotaExceededError
from app.services.storage import get_local_storage

logger = logging.getLogger(__name__)

STAGE_PROGRESS = {
    JobStage.validate.value: 8,
    JobStage.preprocess.value: 20,
    JobStage.transcribe.value: 40,
    JobStage.normalize_transcript.value: 55,
    JobStage.extract_insights.value: 70,
    JobStage.index_transcript.value: 88,
    JobStage.finalize.value: 100,
}


def _set_stage(db: Session, job: Job, meeting: Meeting, stage: JobStage) -> None:
    job.stage = stage.value
    job.progress_percent = STAGE_PROGRESS[stage.value]
    job.status = JobStatus.running.value
    meeting.status = MeetingStatus.processing.value
    db.add(job)
    db.add(meeting)
    db.commit()


def _fail_job(db: Session, job: Job, meeting: Meeting, code: str, message: str) -> None:
    job.status = JobStatus.failed.value
    job.safe_error_code = code
    job.safe_error_message = message
    job.finished_at = datetime.now(UTC)
    meeting.status = MeetingStatus.failed.value
    db.add(job)
    db.add(meeting)
    db.commit()


def run_full_process_job(job_id: str) -> None:
    """Execute a full transcription job. Invoked inline or by RQ."""
    settings = get_settings()
    session_factory = get_session_factory(settings)
    db = session_factory()
    try:
        job = db.get(Job, UUID(job_id))
        if job is None:
            logger.error("Job %s not found", job_id)
            return
        if job.status == JobStatus.cancelled.value:
            return

        meeting = db.scalar(
            select(Meeting)
            .options(selectinload(Meeting.recordings))
            .where(Meeting.id == job.meeting_id)
        )
        if meeting is None:
            job.status = JobStatus.failed.value
            job.safe_error_code = "internal_error"
            job.safe_error_message = "Meeting missing."
            job.finished_at = datetime.now(UTC)
            db.add(job)
            db.commit()
            return

        job.started_at = datetime.now(UTC)
        job.status = JobStatus.running.value
        db.add(job)
        db.commit()

        try:
            _set_stage(db, job, meeting, JobStage.validate)
            recording = _latest_recording(db, meeting.id)
            if recording is None:
                raise AudioProcessingError("invalid_media", "No recording is available.")

            storage = get_local_storage(settings)
            source_path = storage.path_for(recording.storage_key)

            _set_stage(db, job, meeting, JobStage.preprocess)
            with tempfile.TemporaryDirectory(prefix="ama-audio-") as tmp:
                normalized = Path(tmp) / "normalized.wav"
                probe = normalize_audio(source_path, normalized, settings)
                recording.duration_ms = probe.duration_ms
                recording.codec = probe.codec
                meeting.duration_ms = probe.duration_ms
                db.add(recording)
                db.add(meeting)
                db.commit()

                owner = db.get(User, meeting.owner_id)
                if owner is not None:
                    try:
                        quota_service.enforce_audio_minutes_quota(
                            db,
                            owner,
                            settings,
                            additional_ms=probe.duration_ms,
                            as_http=False,
                        )
                    except QuotaExceededError as exc:
                        raise AudioProcessingError("quota_exceeded", exc.message) from exc

                _set_stage(db, job, meeting, JobStage.transcribe)
                provider = get_transcription_provider()
                transcript = asyncio.run(
                    provider.transcribe(
                        normalized,
                        language=meeting.language,
                        diarize=True,
                        prompt_context=meeting.title,
                    )
                )

                _set_stage(db, job, meeting, JobStage.normalize_transcript)
                db.execute(
                    delete(TranscriptSegmentRow).where(
                        TranscriptSegmentRow.meeting_id == meeting.id
                    )
                )
                for segment in transcript.segments:
                    db.add(
                        TranscriptSegmentRow(
                            id=segment.id,
                            meeting_id=meeting.id,
                            ordinal=segment.ordinal,
                            speaker_label=segment.speaker_label,
                            start_ms=segment.start_ms,
                            end_ms=segment.end_ms,
                            text=segment.text,
                            original_text=segment.text,
                            language=segment.language,
                            confidence=segment.confidence,
                            is_user_edited=False,
                            provider_metadata={
                                "model_name": transcript.model_name,
                                "provider": transcript.provider,
                            },
                        )
                    )
                db.commit()

            _set_stage(db, job, meeting, JobStage.extract_insights)
            insight = extract_and_store(db, meeting, template=meeting.meeting_type)
            db.commit()

            _set_stage(db, job, meeting, JobStage.index_transcript)
            chunk_count = index_meeting(db, meeting.id)
            db.commit()

            _set_stage(db, job, meeting, JobStage.finalize)
            job.status = JobStatus.succeeded.value
            job.finished_at = datetime.now(UTC)
            meeting.status = MeetingStatus.ready.value
            if transcript.duration_ms:
                meeting.duration_ms = transcript.duration_ms
            duration_for_usage = int(meeting.duration_ms or recording.duration_ms or 0)
            quota_service.record_audio_usage(db, meeting.owner_id, audio_ms=duration_for_usage)
            job.provider_request_ids = {
                "transcription_model": transcript.model_name,
                "transcription_provider": transcript.provider,
                "insight_version": insight.version,
                "insight_model": insight.model_name,
                "chunk_count": chunk_count,
            }
            db.add(job)
            db.add(meeting)
            db.commit()
        except AudioProcessingError as exc:
            logger.warning("Job %s failed: %s", job_id, exc.message)
            _fail_job(db, job, meeting, exc.code, exc.message)
        except QuotaExceededError as exc:
            logger.warning("Job %s quota failure: %s", job_id, exc.message)
            _fail_job(db, job, meeting, "quota_exceeded", exc.message)
        except MeetingIntelligenceError as exc:
            logger.warning("Job %s insight failure: %s", job_id, exc)
            _fail_job(
                db,
                job,
                meeting,
                "evidence_validation_error",
                "Meeting intelligence failed evidence validation.",
            )
        except Exception:
            logger.exception("Job %s failed unexpectedly", job_id)
            _fail_job(
                db,
                job,
                meeting,
                "internal_error",
                "Processing failed. Please retry later.",
            )
    finally:
        db.close()


def _latest_recording(db: Session, meeting_id: UUID) -> Recording | None:
    return db.scalar(
        select(Recording)
        .where(Recording.meeting_id == meeting_id)
        .order_by(Recording.created_at.desc())
        .limit(1)
    )


def enqueue_or_run_job(job_id: UUID, settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    if cfg.job_runner == "rq":
        from redis import Redis
        from rq import Queue

        from app.workers.tasks import process_meeting_job

        redis_conn = Redis.from_url(cfg.redis_url)
        queue = Queue("meeting-processing", connection=redis_conn)
        queue.enqueue(process_meeting_job, str(job_id), job_timeout="30m")
        return
    run_full_process_job(str(job_id))
