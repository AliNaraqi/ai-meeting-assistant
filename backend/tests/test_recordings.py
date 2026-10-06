"""Recording upload flow tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import bearer_for


def _create_meeting(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/meetings",
        headers=headers,
        json={
            "title": "Upload test",
            "meeting_type": "general",
            "consent_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_recording_upload_complete_and_playback(client: TestClient) -> None:
    headers = bearer_for(client, "uploader@example.com")
    meeting_id = _create_meeting(client, headers)
    payload = b"RIFF....WAVEfmt fake-audio-bytes-for-test" * 20

    initiate = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/initiate",
        headers=headers,
        json={
            "original_filename": "clip.wav",
            "mime_type": "audio/wav",
            "size_bytes": len(payload),
            "source": "upload",
        },
    )
    assert initiate.status_code == 200, initiate.text
    ticket = initiate.json()

    upload = client.put(
        f"/api/v1/meetings/{meeting_id}/recordings/upload",
        headers={**headers, "X-Upload-Token": ticket["upload_token"]},
        content=payload,
    )
    assert upload.status_code == 204, upload.text

    complete = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/complete",
        headers=headers,
        json={
            "upload_token": ticket["upload_token"],
            "storage_key": ticket["storage_key"],
            "size_bytes": len(payload),
        },
    )
    assert complete.status_code == 201, complete.text
    recording_id = complete.json()["id"]

    meeting = client.get(f"/api/v1/meetings/{meeting_id}", headers=headers)
    assert meeting.status_code == 200
    assert meeting.json()["status"] == "uploaded"

    playback = client.get(
        f"/api/v1/meetings/{meeting_id}/recordings/{recording_id}/playback-url",
        headers=headers,
    )
    assert playback.status_code == 200
    media_path = playback.json()["url"].removeprefix("http://testserver")
    media = client.get(media_path)
    assert media.status_code == 200
    assert media.content == payload


def test_upload_requires_consent(client: TestClient) -> None:
    headers = bearer_for(client, "noconsent@example.com")
    created = client.post(
        "/api/v1/meetings",
        headers=headers,
        json={"title": "No consent", "consent_confirmed": False},
    )
    meeting_id = created.json()["id"]
    initiate = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/initiate",
        headers=headers,
        json={
            "original_filename": "clip.webm",
            "mime_type": "audio/webm",
            "size_bytes": 128,
            "source": "browser",
        },
    )
    assert initiate.status_code == 409


def test_reject_unsupported_mime(client: TestClient) -> None:
    headers = bearer_for(client, "badmime@example.com")
    meeting_id = _create_meeting(client, headers)
    initiate = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/initiate",
        headers=headers,
        json={
            "original_filename": "notes.txt",
            "mime_type": "text/plain",
            "size_bytes": 12,
            "source": "upload",
        },
    )
    assert initiate.status_code == 415
