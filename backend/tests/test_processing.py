"""Processing pipeline tests (inline job runner + mock transcription)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import bearer_for


def _upload_meeting(client: TestClient, headers: dict[str, str]) -> str:
    created = client.post(
        "/api/v1/meetings",
        headers=headers,
        json={"title": "Process me", "consent_confirmed": True, "meeting_type": "standup"},
    )
    assert created.status_code == 201, created.text
    meeting_id = created.json()["id"]
    payload = b"fake-audio-content-for-processing-tests" * 10
    initiate = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/initiate",
        headers=headers,
        json={
            "original_filename": "clip.webm",
            "mime_type": "audio/webm",
            "size_bytes": len(payload),
            "source": "browser",
        },
    )
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
    return str(meeting_id)


def test_process_produces_transcript(client: TestClient) -> None:
    headers = bearer_for(client, "processor@example.com")
    meeting_id = _upload_meeting(client, headers)

    process = client.post(f"/api/v1/meetings/{meeting_id}/process", headers=headers)
    assert process.status_code == 202, process.text
    job = process.json()
    assert job["status"] == "succeeded"
    assert job["progress_percent"] == 100

    meeting = client.get(f"/api/v1/meetings/{meeting_id}", headers=headers)
    assert meeting.json()["status"] == "ready"

    transcript = client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=headers)
    assert transcript.status_code == 200, transcript.text
    items = transcript.json()["items"]
    assert len(items) >= 2
    assert items[0]["speaker"]["label"].startswith("speaker_")
    assert items[0]["start_ms"] >= 0
    assert items[0]["end_ms"] >= items[0]["start_ms"]

    insights = client.get(f"/api/v1/meetings/{meeting_id}/insights", headers=headers)
    assert insights.status_code == 200, insights.text
    body = insights.json()
    assert body["one_sentence_summary"]
    assert body["executive_summary"]
    assert isinstance(body["decisions"], list)
    assert isinstance(body["key_points"], list)
    assert all("evidence" in point for point in body["key_points"])

    actions = client.get(f"/api/v1/meetings/{meeting_id}/actions", headers=headers)
    assert actions.status_code == 200, actions.text
    action_rows = actions.json()
    assert len(action_rows) >= 1
    assert action_rows[0]["evidence_segment_ids"]
    assert action_rows[0]["status"] == "open"

    patched = client.patch(
        f"/api/v1/meetings/{meeting_id}/insights",
        headers=headers,
        json={"one_sentence_summary": "Edited one-sentence summary for the meeting."},
    )
    assert patched.status_code == 200
    assert patched.json()["one_sentence_summary"].startswith("Edited")

    action_id = action_rows[0]["id"]
    updated_action = client.patch(
        f"/api/v1/meetings/{meeting_id}/actions/{action_id}",
        headers=headers,
        json={"status": "completed"},
    )
    assert updated_action.status_code == 200
    assert updated_action.json()["status"] == "completed"
    assert updated_action.json()["is_user_edited"] is True


def test_process_requires_uploaded_recording(client: TestClient) -> None:
    headers = bearer_for(client, "draft-only@example.com")
    created = client.post(
        "/api/v1/meetings",
        headers=headers,
        json={"title": "Draft", "consent_confirmed": True},
    )
    meeting_id = created.json()["id"]
    process = client.post(f"/api/v1/meetings/{meeting_id}/process", headers=headers)
    assert process.status_code == 409
