"""Lightweight PII redaction for stored insight text (not raw transcripts)."""

from __future__ import annotations

import re
from typing import Any

from app.schemas.intelligence import MeetingIntelligence

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"
)
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")


def redact_text(value: str) -> str:
    cleaned = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    cleaned = _PHONE_RE.sub("[REDACTED_PHONE]", cleaned)
    cleaned = _CARD_RE.sub("[REDACTED_CARD]", cleaned)
    return cleaned


def _redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_obj(item) for key, item in value.items()}
    return value


def redact_meeting_intelligence(intelligence: MeetingIntelligence) -> MeetingIntelligence:
    """Return a copy with obvious PII scrubbed from insight fields."""
    payload = intelligence.model_dump(mode="python")
    # Keep evidence UUIDs intact; only scrub human-readable strings recursively.
    redacted = _redact_obj(payload)
    return MeetingIntelligence.model_validate(redacted)
