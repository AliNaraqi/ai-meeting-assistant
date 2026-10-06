"""Transcript chunking and embedding index for meeting Q&A."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Meeting, TranscriptChunk, TranscriptSegmentRow, User
from app.config import get_settings
from app.services import quotas as quota_service
from app.services.providers import get_embedding_provider
from app.services.transcript import speaker_display_map

# Approximate tokens as characters/4; keep chunks in the planned 300–700 token band.
TARGET_CHARS = 1_600
OVERLAP_SEGMENTS = 1
EMBEDDING_MODEL = "mock-embed-v1"


@dataclass(frozen=True)
class ChunkDraft:
    first_segment_id: UUID
    last_segment_id: UUID
    start_ms: int
    end_ms: int
    content: str
    token_count: int
    segment_ids: tuple[UUID, ...]


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _format_segment_line(segment: TranscriptSegmentRow, displays: dict[str, str]) -> str:
    speaker = displays.get(segment.speaker_label) or segment.speaker_label
    minutes, seconds = divmod(max(0, segment.start_ms) // 1000, 60)
    return f"[{minutes:02d}:{seconds:02d}] {speaker} ({segment.id}): {segment.text}"


def build_chunk_drafts(
    segments: list[TranscriptSegmentRow],
    displays: dict[str, str],
) -> list[ChunkDraft]:
    if not segments:
        return []

    drafts: list[ChunkDraft] = []
    index = 0
    while index < len(segments):
        bucket: list[TranscriptSegmentRow] = []
        content_parts: list[str] = []
        chars = 0
        cursor = index
        while cursor < len(segments):
            line = _format_segment_line(segments[cursor], displays)
            next_chars = chars + len(line) + 1
            if bucket and next_chars > TARGET_CHARS:
                break
            bucket.append(segments[cursor])
            content_parts.append(line)
            chars = next_chars
            cursor += 1
            if chars >= TARGET_CHARS:
                break

        content = "\n".join(content_parts)
        drafts.append(
            ChunkDraft(
                first_segment_id=bucket[0].id,
                last_segment_id=bucket[-1].id,
                start_ms=bucket[0].start_ms,
                end_ms=bucket[-1].end_ms,
                content=content,
                token_count=estimate_tokens(content),
                segment_ids=tuple(item.id for item in bucket),
            )
        )
        if cursor >= len(segments):
            break
        index = max(index + 1, cursor - OVERLAP_SEGMENTS)

    return drafts


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
    return dot / (left_norm * right_norm)


def index_meeting(db: Session, meeting_id: UUID) -> int:
    """Replace transcript chunks for a meeting. Returns chunk count."""
    segments = list(
        db.scalars(
            select(TranscriptSegmentRow)
            .where(TranscriptSegmentRow.meeting_id == meeting_id)
            .order_by(TranscriptSegmentRow.ordinal.asc())
        ).all()
    )
    displays = speaker_display_map(db, meeting_id)
    drafts = build_chunk_drafts(segments, displays)

    db.execute(delete(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting_id))
    if not drafts:
        db.flush()
        return 0

    settings = get_settings()
    meeting = db.get(Meeting, meeting_id)
    owner = db.get(User, meeting.owner_id) if meeting is not None else None
    estimated = sum(draft.token_count for draft in drafts) + 64
    if owner is not None:
        quota_service.enforce_llm_token_quota(
            db,
            owner,
            settings,
            additional_tokens=estimated,
            as_http=False,
        )

    provider = get_embedding_provider()
    vectors = asyncio.run(provider.embed([draft.content for draft in drafts]))
    model_name = getattr(provider, "model_name", EMBEDDING_MODEL)

    for draft, vector in zip(drafts, vectors, strict=True):
        db.add(
            TranscriptChunk(
                id=uuid4(),
                meeting_id=meeting_id,
                first_segment_id=draft.first_segment_id,
                last_segment_id=draft.last_segment_id,
                start_ms=draft.start_ms,
                end_ms=draft.end_ms,
                content=draft.content,
                token_count=draft.token_count,
                embedding=list(vector),
                embedding_model=model_name,
            )
        )
    if owner is not None:
        quota_service.record_llm_tokens(db, owner.id, tokens=estimated)
    db.flush()
    return len(drafts)


def retrieve_chunks(
    db: Session,
    meeting_id: UUID,
    *,
    question: str,
    top_k: int = 3,
) -> list[TranscriptChunk]:
    chunks = list(
        db.scalars(
            select(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting_id)
        ).all()
    )
    if not chunks:
        return []

    provider = get_embedding_provider()
    query_vector = asyncio.run(provider.embed([question]))[0]
    ranked = sorted(
        chunks,
        key=lambda chunk: cosine_similarity(
            [float(v) for v in chunk.embedding if isinstance(v, (int, float, str))],
            query_vector,
        ),
        reverse=True,
    )
    return ranked[: max(1, top_k)]
