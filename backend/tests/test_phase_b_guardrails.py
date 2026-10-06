"""Phase B guardrails: monthly quotas, usage endpoint, and PII redaction."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import get_session_factory
from app.models import User
from app.services.quotas import get_or_create_usage_month, record_audio_usage, record_llm_tokens
from app.services.redaction import redact_text
from sqlalchemy import select
from tests.conftest import bearer_for
from tests.test_processing import _upload_meeting


def test_redact_text_scrubs_email_phone_and_card() -> None:
    raw = (
        "Email jane.doe@acme.co or call +1 (415) 555-1212. "
        "Card 4111 1111 1111 1111 ends soon."
    )
    cleaned = redact_text(raw)
    assert "jane.doe@acme.co" not in cleaned
    assert "[REDACTED_EMAIL]" in cleaned
    assert "555-1212" not in cleaned
    assert "[REDACTED_PHONE]" in cleaned
    assert "4111 1111 1111 1111" not in cleaned
    assert "[REDACTED_CARD]" in cleaned


def test_me_usage_endpoint_and_audio_quota_429(client: TestClient) -> None:
    headers = bearer_for(client, "quota-user@example.com")

    usage = client.get("/api/v1/me/usage", headers=headers)
    assert usage.status_code == 200, usage.text
    body = usage.json()
    assert body["audio_minutes_limit"] == 30
    assert body["audio_minutes_remaining"] == 30
    assert body["llm_tokens_remaining"] > 0
    assert "period" in body

    session = get_session_factory()()
    try:
        user = session.scalar(select(User).where(User.email == "quota-user@example.com"))
        assert user is not None
        # Exhaust the monthly audio budget (30 minutes).
        record_audio_usage(session, user.id, audio_ms=30 * 60_000)
        session.commit()
    finally:
        session.close()

    meeting_id = _upload_meeting(client, headers)
    blocked = client.post(f"/api/v1/meetings/{meeting_id}/process", headers=headers)
    assert blocked.status_code == 429, blocked.text
    detail = blocked.json()["error"]
    assert detail["code"] == "quota_exceeded"
    assert "audio" in detail["message"].lower() or "minutes" in detail["message"].lower()

    usage_after = client.get("/api/v1/me/usage", headers=headers)
    assert usage_after.status_code == 200
    assert usage_after.json()["audio_minutes_remaining"] == 0.0


def test_llm_token_quota_blocks_questions(client: TestClient) -> None:
    headers = bearer_for(client, "token-quota@example.com")
    meeting_id = _upload_meeting(client, headers)
    process = client.post(f"/api/v1/meetings/{meeting_id}/process", headers=headers)
    assert process.status_code == 202, process.text
    assert process.json()["status"] == "succeeded"

    session = get_session_factory()()
    try:
        user = session.scalar(select(User).where(User.email == "token-quota@example.com"))
        assert user is not None
        row = get_or_create_usage_month(session, user.id)
        # Leave no room for another LLM call.
        record_llm_tokens(session, user.id, tokens=500_000 - int(row.llm_tokens))
        session.commit()
    finally:
        session.close()

    asked = client.post(
        f"/api/v1/meetings/{meeting_id}/questions",
        headers=headers,
        json={"question": "What was decided?"},
    )
    assert asked.status_code == 429, asked.text
    assert asked.json()["error"]["code"] == "quota_exceeded"
