"""Phase D: public status page and IP upload rate limits."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.services.rate_limit import reset_memory_limits_for_tests
from tests.conftest import bearer_for


def test_status_json_and_page(client: TestClient) -> None:
    page = client.get("/status")
    assert page.status_code == 200
    assert b"Ops status" in page.content

    status = client.get("/api/v1/status")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["provider_mode"] in {"mock", "openai"}
    assert body["status"] == "ok"
    assert "queue_length" in body
    assert "last_job_at" in body
    assert body["version"]


def test_upload_rate_limit_per_ip(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("MAX_UPLOADS_PER_IP_PER_DAY", "2")
    get_settings.cache_clear()
    reset_memory_limits_for_tests()

    headers = {
        **bearer_for(client, "rate-limit@example.com"),
        # Isolate this test from other suites / Redis keys.
        "X-Forwarded-For": "203.0.113.50",
    }
    created = client.post(
        "/api/v1/meetings",
        headers=headers,
        json={"title": "Rate limit meeting", "consent_confirmed": True},
    )
    assert created.status_code == 201, created.text
    meeting_id = created.json()["id"]

    payload = {
        "original_filename": "clip.webm",
        "mime_type": "audio/webm",
        "size_bytes": 1024,
        "source": "upload",
    }

    assert (
        client.post(
            f"/api/v1/meetings/{meeting_id}/recordings/initiate",
            headers=headers,
            json=payload,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/meetings/{meeting_id}/recordings/initiate",
            headers=headers,
            json=payload,
        ).status_code
        == 200
    )
    blocked = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/initiate",
        headers=headers,
        json=payload,
    )
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"]["code"] == "rate_limited"

    monkeypatch.setenv("MAX_UPLOADS_PER_IP_PER_DAY", "0")
    get_settings.cache_clear()
    reset_memory_limits_for_tests()
