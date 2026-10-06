"""Persist and serve meeting intelligence bundles."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import (
    ActionItemRow,
    ActionItemStatus,
    ActionPriority,
    Meeting,
    MeetingInsight,
    Participant,
    TranscriptSegmentRow,
    User,
)
from app.prompts.extraction import PROMPT_VERSION
from app.schemas.intelligence import MeetingIntelligence
from app.schemas.transcript import MeetingMetadata, TranscriptSegment
from app.services import meetings as meeting_service
from app.services import quotas as quota_service
from app.services.meeting_intelligence import MeetingIntelligenceError
from app.services.providers import get_meeting_intelligence_provider
from app.services.quotas import estimate_tokens
from app.services.redaction import redact_meeting_intelligence, redact_text


def _segments_for_meeting(db: Session, meeting_id: UUID) -> list[TranscriptSegment]:
    rows = list(
        db.scalars(
            select(TranscriptSegmentRow)
            .where(TranscriptSegmentRow.meeting_id == meeting_id)
            .order_by(TranscriptSegmentRow.ordinal.asc())
        ).all()
    )
    return [
        TranscriptSegment(
            id=row.id,
            ordinal=row.ordinal,
            speaker_label=row.speaker_label,
            start_ms=row.start_ms,
            end_ms=row.end_ms,
            text=row.text,
            language=row.language,
            confidence=float(row.confidence) if row.confidence is not None else None,
        )
        for row in rows
    ]


def _metadata_for_meeting(db: Session, meeting: Meeting) -> MeetingMetadata:
    aliases = list(
        db.scalars(
            select(Participant.display_name).where(Participant.meeting_id == meeting.id)
        ).all()
    )
    return MeetingMetadata.model_validate(
        {
            "title": meeting.title,
            "meeting_type": meeting.meeting_type,
            "language": meeting.language,
            "occurred_at": meeting.occurred_at,
            "participant_aliases": aliases,
            "description": meeting.description,
        }
    )


def persist_intelligence(
    db: Session,
    meeting: Meeting,
    intelligence: MeetingIntelligence,
    *,
    model_name: str,
    prompt_version: str,
    settings: Settings | None = None,
) -> MeetingInsight:
    cfg = settings or get_settings()
    if cfg.redact_pii:
        intelligence = redact_meeting_intelligence(intelligence)

    current_version = db.scalar(
        select(func.coalesce(func.max(MeetingInsight.version), 0)).where(
            MeetingInsight.meeting_id == meeting.id
        )
    )
    version = int(current_version or 0) + 1

    # Replace generated actions for this regeneration path.
    db.execute(delete(ActionItemRow).where(ActionItemRow.meeting_id == meeting.id))

    insight = MeetingInsight(
        id=uuid4(),
        meeting_id=meeting.id,
        version=version,
        schema_version=intelligence.schema_version,
        model_name=model_name,
        prompt_version=prompt_version,
        one_sentence_summary=intelligence.one_sentence_summary,
        executive_summary=intelligence.executive_summary,
        key_points=[item.model_dump(mode="json") for item in intelligence.key_points],
        decisions=[item.model_dump(mode="json") for item in intelligence.decisions],
        questions=[item.model_dump(mode="json") for item in intelligence.questions],
        risks=[item.model_dump(mode="json") for item in intelligence.risks],
        topics=[item.model_dump(mode="json") for item in intelligence.topics],
        follow_up_email=intelligence.follow_up_email.model_dump(mode="json"),
        tags=list(intelligence.tags),
        generated_at=datetime.now(UTC),
    )
    db.add(insight)

    for action in intelligence.action_items:
        db.add(
            ActionItemRow(
                id=uuid4(),
                meeting_id=meeting.id,
                source_insight_version=version,
                task=action.task,
                owner_text=action.owner,
                due_date=action.due_date,
                due_date_text=action.due_date_text,
                priority=ActionPriority.medium.value,
                status=ActionItemStatus.open.value,
                evidence_segment_ids=[str(ref.segment_id) for ref in action.evidence],
                confidence_label=action.confidence_label,
                is_user_edited=False,
            )
        )

    meeting.summary_version = version
    db.add(meeting)
    db.flush()
    db.refresh(insight)
    return insight


def extract_and_store(
    db: Session,
    meeting: Meeting,
    *,
    template: str | None = None,
) -> MeetingInsight:
    segments = _segments_for_meeting(db, meeting.id)
    if not segments:
        raise MeetingIntelligenceError("Cannot extract insights without a transcript.")

    settings = get_settings()
    owner = db.get(User, meeting.owner_id)
    metadata = _metadata_for_meeting(db, meeting)
    provider = get_meeting_intelligence_provider()
    # Rough pre-call budget: transcript + prompts.
    estimated = estimate_tokens(
        metadata.title,
        *(segment.text for segment in segments),
    ) + 1_500
    if owner is not None:
        quota_service.enforce_llm_token_quota(
            db,
            owner,
            settings,
            additional_tokens=estimated,
            as_http=False,
        )

    intelligence = asyncio.run(
        provider.extract(
            metadata,
            segments,
            template or meeting.meeting_type,
        )
    )
    model_name = getattr(provider, "model_name", "mock-meeting-intelligence")
    prompt_version = getattr(provider, "prompt_version", PROMPT_VERSION)
    insight = persist_intelligence(
        db,
        meeting,
        intelligence,
        model_name=str(model_name),
        prompt_version=str(prompt_version),
        settings=settings,
    )
    if owner is not None:
        used = estimate_tokens(
            intelligence.one_sentence_summary,
            intelligence.executive_summary,
            *(item.task for item in intelligence.action_items),
            *(item.text for item in intelligence.decisions),
        ) + estimated
        quota_service.record_llm_tokens(db, owner.id, tokens=used)
    return insight


def get_active_insight(db: Session, owner: User, meeting_id: UUID) -> MeetingInsight:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    insight = db.scalar(
        select(MeetingInsight)
        .where(MeetingInsight.meeting_id == meeting_id)
        .order_by(MeetingInsight.version.desc())
        .limit(1)
    )
    if insight is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "not_found",
                    "message": "No insights are available for this meeting yet.",
                }
            },
        )
    return insight


def update_insight_summaries(
    db: Session,
    owner: User,
    meeting_id: UUID,
    *,
    one_sentence_summary: str | None,
    executive_summary: str | None,
) -> MeetingInsight:
    insight = get_active_insight(db, owner, meeting_id)
    settings = get_settings()
    if one_sentence_summary is not None:
        text = one_sentence_summary.strip()
        insight.one_sentence_summary = redact_text(text) if settings.redact_pii else text
    if executive_summary is not None:
        text = executive_summary.strip()
        insight.executive_summary = redact_text(text) if settings.redact_pii else text
    db.add(insight)
    db.flush()
    db.refresh(insight)
    return insight


def list_actions(db: Session, owner: User, meeting_id: UUID) -> list[ActionItemRow]:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    return list(
        db.scalars(
            select(ActionItemRow)
            .where(ActionItemRow.meeting_id == meeting_id)
            .order_by(ActionItemRow.created_at.asc())
        ).all()
    )


def get_owned_action(db: Session, owner: User, meeting_id: UUID, action_id: UUID) -> ActionItemRow:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    action = db.scalar(
        select(ActionItemRow).where(
            ActionItemRow.id == action_id,
            ActionItemRow.meeting_id == meeting_id,
        )
    )
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Action item not found."}},
        )
    return action


def regenerate_insights(
    db: Session,
    owner: User,
    meeting_id: UUID,
    *,
    template: str | None,
) -> MeetingInsight:
    from app.services.quotas import QuotaExceededError

    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    try:
        return extract_and_store(db, meeting, template=template)
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "quota_exceeded", "message": exc.message}},
        ) from exc
