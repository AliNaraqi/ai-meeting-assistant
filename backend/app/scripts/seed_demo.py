"""Seed a synthetic demo meeting for local / staging demos.

Usage (from backend/ with APP env configured):

    python -m app.scripts.seed_demo

Or:

    PYTHONPATH=. python ../scripts/seed_demo.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory, reset_engine
from app.models import (
    Meeting,
    MeetingStatus,
    MeetingType,
    Participant,
    Recording,
    TranscriptSegmentRow,
    User,
)
from app.schemas.transcript import TranscriptSegment
from app.services.demo import DEMO_TITLE
from app.services.indexing import index_meeting
from app.services.insights import extract_and_store
from app.services.storage import get_local_storage
from app.services.transcription import MockTranscriptionProvider

logger = logging.getLogger("seed_demo")

DEMO_EMAIL = "demo@example.com"
# Back-compat alias used by older docs/tests.
LEGACY_DEMO_TITLES = ("Aurora weekly sync (demo)",)


async def _build_transcript() -> list[TranscriptSegment]:
    provider = MockTranscriptionProvider()
    tmp = Path("/tmp") / f"ama-demo-{uuid4().hex}.wav"
    tmp.write_bytes(b"RIFF....WAVE")
    try:
        result = await provider.transcribe(
            tmp, language="en", diarize=True, prompt_context=DEMO_TITLE
        )
    finally:
        tmp.unlink(missing_ok=True)
    return list(result.segments)


def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine from sync code, even inside FastAPI's event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Lifespan / request context already has a loop — run in a worker thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _find_demo_meeting(db, user_id) -> Meeting | None:
    meeting = db.scalar(
        select(Meeting).where(
            Meeting.owner_id == user_id,
            Meeting.title == DEMO_TITLE,
            Meeting.deleted_at.is_(None),
        )
    )
    if meeting is not None:
        return meeting
    for title in LEGACY_DEMO_TITLES:
        meeting = db.scalar(
            select(Meeting).where(
                Meeting.owner_id == user_id,
                Meeting.title == title,
                Meeting.deleted_at.is_(None),
            )
        )
        if meeting is not None:
            meeting.title = DEMO_TITLE
            db.add(meeting)
            db.flush()
            return meeting
    return None


def seed_demo(*, force: bool = False, reset: bool = False) -> str:
    """Create or return the shared 'Try me' demo meeting.

    ``reset=True`` disposes the SQLAlchemy engine (CLI only — never from app lifespan).
    """
    settings = get_settings()
    if reset:
        reset_engine()
    session_factory = get_session_factory(settings)
    db = session_factory()
    demo_email = settings.demo_user_email.lower()
    try:
        user = db.scalar(select(User).where(User.email == demo_email))
        if user is None:
            user = User(email=demo_email, display_name="Demo User")
            db.add(user)
            db.flush()

        existing = _find_demo_meeting(db, user.id)
        if existing is not None and not force:
            # Ensure insights + chunks exist even if an older partial seed left a shell.
            if existing.status != MeetingStatus.ready.value:
                existing.status = MeetingStatus.ready.value
                db.add(existing)
            if existing.summary_version < 1:
                extract_and_store(db, existing, template=existing.meeting_type)
                index_meeting(db, existing.id)
            db.commit()
            logger.info("Demo meeting already exists: %s", existing.id)
            return str(existing.id)
        if existing is not None and force:
            db.delete(existing)
            db.flush()

        meeting = Meeting(
            owner_id=user.id,
            title=DEMO_TITLE,
            description=(
                "Shared portfolio demo — fully processed transcript, insights, and Q&A. "
                "Read-only for visitors."
            ),
            meeting_type=MeetingType.standup.value,
            language="en",
            status=MeetingStatus.ready.value,
            consent_confirmed_at=datetime.now(UTC),
        )
        meeting.participants.append(
            Participant(display_name="Mina", role="organizer", speaker_label="speaker_0")
        )
        meeting.participants.append(
            Participant(display_name="Noah", role="engineer", speaker_label="speaker_1")
        )
        db.add(meeting)
        db.flush()

        storage = get_local_storage(settings)
        storage_key = f"meetings/{meeting.id}/demo.webm"
        payload = b"demo-audio-bytes-not-real" * 20
        storage.save_bytes(storage_key, payload)
        db.add(
            Recording(
                meeting_id=meeting.id,
                storage_bucket="local-meeting-audio",
                storage_key=storage_key,
                original_filename="demo.webm",
                mime_type="audio/webm",
                size_bytes=len(payload),
                source="upload",
            )
        )

        import asyncio

        segments = _run_coro(_build_transcript())
        for segment in segments:
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
                )
            )
        db.flush()

        extract_and_store(db, meeting, template=meeting.meeting_type)
        index_meeting(db, meeting.id)
        db.commit()
        logger.info("Seeded demo meeting %s for %s", meeting.id, demo_email)
        return str(meeting.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Seed synthetic demo meeting")
    parser.add_argument("--force", action="store_true", help="Replace existing demo meeting")
    args = parser.parse_args()
    meeting_id = seed_demo(force=args.force, reset=True)
    print(meeting_id)


if __name__ == "__main__":
    main()
