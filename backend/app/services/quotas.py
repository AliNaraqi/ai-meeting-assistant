"""User quota checks and monthly usage accounting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ChatMessage, ChatRole, Meeting, UsageMonth, User


def current_period(now: datetime | None = None) -> str:
    stamp = now or datetime.now(UTC)
    return f"{stamp.year:04d}-{stamp.month:02d}"


def estimate_tokens(*texts: str) -> int:
    total_chars = sum(len(text or "") for text in texts)
    return max(1, (total_chars + 3) // 4) if total_chars else 0


class QuotaExceededError(RuntimeError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _quota_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"error": {"code": "quota_exceeded", "message": message}},
    )


def get_or_create_usage_month(db: Session, user_id, period: str | None = None) -> UsageMonth:
    period_key = period or current_period()
    row = db.scalar(
        select(UsageMonth).where(UsageMonth.user_id == user_id, UsageMonth.period == period_key)
    )
    if row is not None:
        return row
    row = UsageMonth(
        id=uuid4(),
        user_id=user_id,
        period=period_key,
        audio_ms=0,
        llm_tokens=0,
    )
    db.add(row)
    db.flush()
    return row


def usage_snapshot(db: Session, owner: User, settings: Settings) -> dict[str, object]:
    period = current_period()
    row = get_or_create_usage_month(db, owner.id, period)
    audio_minutes_used = row.audio_ms / 60_000
    audio_cap = float(settings.max_audio_minutes_per_user_per_month)
    token_cap = int(settings.max_llm_tokens_per_user_per_month)
    meetings_count = db.scalar(
        select(func.count())
        .select_from(Meeting)
        .where(Meeting.owner_id == owner.id, Meeting.deleted_at.is_(None))
    ) or 0
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    questions_today = db.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(
            ChatMessage.user_id == owner.id,
            ChatMessage.role == ChatRole.user.value,
            ChatMessage.created_at >= day_start,
        )
    ) or 0
    return {
        "period": period,
        "audio_minutes_used": round(audio_minutes_used, 2),
        "audio_minutes_limit": settings.max_audio_minutes_per_user_per_month,
        "audio_minutes_remaining": max(0.0, round(audio_cap - audio_minutes_used, 2)),
        "llm_tokens_used": int(row.llm_tokens),
        "llm_tokens_limit": token_cap,
        "llm_tokens_remaining": max(0, token_cap - int(row.llm_tokens)),
        "meetings_used": int(meetings_count),
        "meetings_limit": settings.max_meetings_per_user,
        "meetings_remaining": max(0, settings.max_meetings_per_user - int(meetings_count)),
        "questions_today_used": int(questions_today),
        "questions_today_limit": settings.max_questions_per_day,
        "questions_today_remaining": max(
            0, settings.max_questions_per_day - int(questions_today)
        ),
    }


def enforce_meeting_quota(db: Session, owner: User, settings: Settings) -> None:
    count = db.scalar(
        select(func.count())
        .select_from(Meeting)
        .where(Meeting.owner_id == owner.id, Meeting.deleted_at.is_(None))
    )
    if (count or 0) >= settings.max_meetings_per_user:
        raise _quota_error(
            f"Meeting limit reached ({settings.max_meetings_per_user}). "
            "Delete an old meeting to create another."
        )


def enforce_question_quota(db: Session, owner: User, settings: Settings) -> None:
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    count = db.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(
            ChatMessage.user_id == owner.id,
            ChatMessage.role == ChatRole.user.value,
            ChatMessage.created_at >= day_start,
        )
    )
    if (count or 0) >= settings.max_questions_per_day:
        raise _quota_error(
            f"Daily question limit reached ({settings.max_questions_per_day}). "
            "Try again tomorrow."
        )


def enforce_audio_minutes_quota(
    db: Session,
    owner: User,
    settings: Settings,
    *,
    additional_ms: int = 0,
    as_http: bool = True,
) -> None:
    row = get_or_create_usage_month(db, owner.id)
    limit_ms = settings.max_audio_minutes_per_user_per_month * 60_000
    used = int(row.audio_ms)
    message = (
        f"Monthly audio limit reached "
        f"({settings.max_audio_minutes_per_user_per_month} minutes). "
        "Try again next month."
    )
    exceed_message = (
        f"This meeting would exceed your monthly audio limit "
        f"({settings.max_audio_minutes_per_user_per_month} minutes)."
    )
    if used >= limit_ms:
        if as_http:
            raise _quota_error(message)
        raise QuotaExceededError(message)
    if additional_ms > 0 and used + additional_ms > limit_ms:
        if as_http:
            raise _quota_error(exceed_message)
        raise QuotaExceededError(exceed_message)


def enforce_llm_token_quota(
    db: Session,
    owner: User,
    settings: Settings,
    *,
    additional_tokens: int,
    as_http: bool = True,
) -> None:
    row = get_or_create_usage_month(db, owner.id)
    projected = int(row.llm_tokens) + max(0, additional_tokens)
    if projected > settings.max_llm_tokens_per_user_per_month:
        message = (
            f"Monthly LLM token limit reached "
            f"({settings.max_llm_tokens_per_user_per_month} tokens). "
            "Try again next month."
        )
        if as_http:
            raise _quota_error(message)
        raise QuotaExceededError(message)


def record_audio_usage(db: Session, owner_id, *, audio_ms: int) -> None:
    if audio_ms <= 0:
        return
    row = get_or_create_usage_month(db, owner_id)
    row.audio_ms = int(row.audio_ms) + int(audio_ms)
    db.add(row)
    db.flush()


def record_llm_tokens(db: Session, owner_id, *, tokens: int) -> None:
    if tokens <= 0:
        return
    row = get_or_create_usage_month(db, owner_id)
    row.llm_tokens = int(row.llm_tokens) + int(tokens)
    db.add(row)
    db.flush()


def seconds_until_question_reset() -> int:
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))
