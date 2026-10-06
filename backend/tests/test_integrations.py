"""Phase 8 integrations: share links, ICS import, export formats, templates."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.calendar_import import parse_ics_event
from tests.conftest import bearer_for
from tests.test_processing import _upload_meeting


def _ready_meeting(client: TestClient, headers: dict[str, str]) -> str:
    meeting_id = _upload_meeting(client, headers)
    process = client.post(f"/api/v1/meetings/{meeting_id}/process", headers=headers)
    assert process.status_code == 202, process.text
    return meeting_id


def test_share_link_public_access_and_revoke(client: TestClient) -> None:
    headers = bearer_for(client, "share@example.com")
    meeting_id = _ready_meeting(client, headers)

    created = client.post(
        f"/api/v1/meetings/{meeting_id}/share-links",
        headers=headers,
        json={"expires_in_hours": 24, "include_transcript": True, "include_insights": True},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["url"].endswith(f"/share/{body['token']}")

    public = client.get(f"/api/v1/share/{body['token']}")
    assert public.status_code == 200, public.text
    shared = public.json()
    assert shared["title"]
    assert shared["insights"]
    assert shared["transcript"]

    page = client.get(f"/share/{body['token']}")
    assert page.status_code == 200
    assert b"share.js" in page.content

    revoked = client.delete(
        f"/api/v1/meetings/{meeting_id}/share-links/{body['id']}",
        headers=headers,
    )
    assert revoked.status_code == 204
    gone = client.get(f"/api/v1/share/{body['token']}")
    assert gone.status_code == 404


def test_ics_import_creates_meeting(client: TestClient) -> None:
    headers = bearer_for(client, "ics@example.com")
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:aurora-sync-001@example.com
DTSTART:20260809T170000Z
SUMMARY:Aurora calendar sync
LOCATION:Zoom
DESCRIPTION:Weekly project check-in
END:VEVENT
END:VCALENDAR
"""
    created = client.post(
        "/api/v1/meetings/from-ics",
        headers=headers,
        json={"ics_text": ics, "consent_confirmed": True, "meeting_type": "standup"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Aurora calendar sync"
    assert body["location"] == "Zoom"
    assert body["calendar_event_uid"] == "aurora-sync-001@example.com"
    assert body["calendar_provider"] == "ics"
    assert body["meeting_type"] == "standup"


def test_parse_ics_requires_vevent() -> None:
    from fastapi import HTTPException

    try:
        parse_ics_event("BEGIN:VCALENDAR\nEND:VCALENDAR\n")
        raise AssertionError("expected validation failure")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_integration_exports_and_templates(client: TestClient) -> None:
    headers = bearer_for(client, "exports@example.com")
    meeting_id = _ready_meeting(client, headers)

    templates = client.get("/api/v1/templates")
    assert templates.status_code == 200
    ids = {item["id"] for item in templates.json()}
    assert {"general", "standup", "interview"}.issubset(ids)

    for fmt in ("slack", "notion", "actions_csv"):
        exported = client.post(
            f"/api/v1/meetings/{meeting_id}/exports",
            headers=headers,
            json={"format": fmt, "include_transcript": False},
        )
        assert exported.status_code == 200, exported.text
        assert exported.json()["content"]
