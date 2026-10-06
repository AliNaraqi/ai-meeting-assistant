"""Quotas, retention, and request-id safety tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.models import Recording
from app.services.retention import purge_expired_audio
from app.services.storage import get_local_storage
from tests.conftest import bearer_for
from tests.test_processing import _upload_meeting


def test_health_includes_version_and_request_id(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "test-req-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert response.headers.get("X-Request-ID") == "test-req-1"


def test_meeting_quota_enforced(client: TestClient, monkeypatch: object) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("MAX_MEETINGS_PER_USER", "1")  # type: ignore[attr-defined]
    get_settings.cache_clear()
    headers = bearer_for(client, "quota-meetings@example.com")

    first = client.post(
        "/api/v1/meetings",
        headers=headers,
        json={"title": "First", "consent_confirmed": True},
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/v1/meetings",
        headers=headers,
        json={"title": "Second", "consent_confirmed": True},
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "quota_exceeded"
    get_settings.cache_clear()


def test_question_quota_enforced(client: TestClient, monkeypatch: object) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("MAX_QUESTIONS_PER_DAY", "1")  # type: ignore[attr-defined]
    get_settings.cache_clear()
    headers = bearer_for(client, "quota-questions@example.com")
    meeting_id = _upload_meeting(client, headers)
    process = client.post(f"/api/v1/meetings/{meeting_id}/process", headers=headers)
    assert process.status_code == 202

    first = client.post(
        f"/api/v1/meetings/{meeting_id}/questions",
        headers=headers,
        json={"question": "Who will send the revised dataset?"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/meetings/{meeting_id}/questions",
        headers=headers,
        json={"question": "Did we decide to use Azure for staging?"},
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "quota_exceeded"
    get_settings.cache_clear()


def test_purge_expired_audio(client: TestClient) -> None:
    headers = bearer_for(client, "retention@example.com")
    meeting_id = _upload_meeting(client, headers)

    settings = get_settings()
    db = get_session_factory(settings)()
    try:
        recording = db.scalar(
            select(Recording).where(Recording.meeting_id == UUID(meeting_id))
        )
        assert recording is not None
        path = get_local_storage(settings).path_for(recording.storage_key)
        assert path.exists()
        recording.retention_until = datetime.now(UTC) - timedelta(days=1)
        db.add(recording)
        db.commit()
        result = purge_expired_audio(db, settings)
        db.commit()
        assert result["deleted_rows"] >= 1
        assert not path.exists()
    finally:
        db.close()
