"""Phase C: shared demo login and read-only guardrails."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.demo import DEMO_TITLE
from tests.conftest import bearer_for


def test_demo_login_opens_try_me_meeting(client: TestClient) -> None:
    response = client.post("/api/v1/auth/demo-login")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "demo@example.com"
    assert body["read_only"] is True
    assert body["meeting_id"]
    assert body["access_token"]

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    meeting = client.get(f"/api/v1/meetings/{body['meeting_id']}", headers=headers)
    assert meeting.status_code == 200, meeting.text
    assert meeting.json()["title"] == DEMO_TITLE
    assert meeting.json()["status"] == "ready"

    insights = client.get(f"/api/v1/meetings/{body['meeting_id']}/insights", headers=headers)
    assert insights.status_code == 200, insights.text
    assert insights.json()["one_sentence_summary"]


def test_demo_user_is_read_only(client: TestClient) -> None:
    demo = client.post("/api/v1/auth/demo-login")
    assert demo.status_code == 200, demo.text
    headers = {"Authorization": f"Bearer {demo.json()['access_token']}"}
    meeting_id = demo.json()["meeting_id"]

    deleted = client.delete(f"/api/v1/meetings/{meeting_id}", headers=headers)
    assert deleted.status_code == 403, deleted.text
    assert deleted.json()["error"]["code"] == "demo_read_only"

    created = client.post(
        "/api/v1/meetings",
        headers=headers,
        json={"title": "Should fail", "consent_confirmed": True},
    )
    assert created.status_code == 403

    # Q&A and export remain available for the demo experience.
    asked = client.post(
        f"/api/v1/meetings/{meeting_id}/questions",
        headers=headers,
        json={"question": "What decisions were made?"},
    )
    assert asked.status_code == 200, asked.text

    exported = client.post(
        f"/api/v1/meetings/{meeting_id}/exports",
        headers=headers,
        json={"format": "markdown", "include_transcript": True},
    )
    assert exported.status_code == 200, exported.text


def test_regular_user_can_still_mutate(client: TestClient) -> None:
    headers = bearer_for(client, "writer@example.com")
    created = client.post(
        "/api/v1/meetings",
        headers=headers,
        json={"title": "Writable meeting", "consent_confirmed": True},
    )
    assert created.status_code == 201, created.text
