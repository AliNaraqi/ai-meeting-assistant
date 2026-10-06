"""Authorized meeting CRUD tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import bearer_for


def test_meeting_crud_and_owner_isolation(client: TestClient) -> None:
    headers_a = bearer_for(client, "owner-a@example.com")
    headers_b = bearer_for(client, "owner-b@example.com")

    create = client.post(
        "/api/v1/meetings",
        headers=headers_a,
        json={
            "title": "Project Aurora weekly sync",
            "description": "Weekly status",
            "meeting_type": "standup",
            "language": "en",
            "consent_confirmed": True,
            "participants": [
                {"display_name": "Mina", "role": "Project manager"},
                {"display_name": "Noah", "role": "Data engineer"},
            ],
        },
    )
    assert create.status_code == 201, create.text
    meeting = create.json()
    meeting_id = meeting["id"]
    assert meeting["status"] == "draft"
    assert meeting["consent_confirmed_at"] is not None
    assert len(meeting["participants"]) == 2

    listed = client.get("/api/v1/meetings", headers=headers_a)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1

    other_list = client.get("/api/v1/meetings", headers=headers_b)
    assert other_list.status_code == 200
    assert other_list.json()["items"] == []

    forbidden = client.get(f"/api/v1/meetings/{meeting_id}", headers=headers_b)
    assert forbidden.status_code == 404

    patched = client.patch(
        f"/api/v1/meetings/{meeting_id}",
        headers=headers_a,
        json={"title": "Aurora sync (updated)"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Aurora sync (updated)"

    deleted = client.delete(f"/api/v1/meetings/{meeting_id}", headers=headers_a)
    assert deleted.status_code == 204

    missing = client.get(f"/api/v1/meetings/{meeting_id}", headers=headers_a)
    assert missing.status_code == 404


def test_unauthenticated_meeting_access(client: TestClient) -> None:
    response = client.get("/api/v1/meetings")
    assert response.status_code == 401


def test_unknown_meeting_is_hidden(client: TestClient) -> None:
    headers = bearer_for(client, "mina@example.com")
    response = client.get(f"/api/v1/meetings/{uuid4()}", headers=headers)
    assert response.status_code == 404
