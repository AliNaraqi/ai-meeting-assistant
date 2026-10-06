"""Meeting workspace APIs: search, rename, export, delete with storage cleanup."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import Meeting, MeetingShareLink, TranscriptChunk
from tests.conftest import bearer_for
from tests.test_processing import _upload_meeting


def _ready_meeting(client: TestClient, headers: dict[str, str]) -> str:
    meeting_id = _upload_meeting(client, headers)
    process = client.post(f"/api/v1/meetings/{meeting_id}/process", headers=headers)
    assert process.status_code == 202, process.text
    assert process.json()["status"] == "succeeded"
    return meeting_id


def test_search_rename_export_and_delete(client: TestClient) -> None:
    headers = bearer_for(client, "workspace@example.com")
    meeting_id = _ready_meeting(client, headers)

    transcript = client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=headers)
    assert transcript.status_code == 200
    items = transcript.json()["items"]
    assert items
    segment_id = items[0]["id"]
    label = items[0]["speaker"]["label"]
    needle = items[0]["text"].split()[0]

    search = client.get(
        f"/api/v1/meetings/{meeting_id}/transcript/search",
        headers=headers,
        params={"q": needle},
    )
    assert search.status_code == 200, search.text
    assert any(row["id"] == segment_id for row in search.json()["items"])

    patched = client.patch(
        f"/api/v1/meetings/{meeting_id}/transcript/segments/{segment_id}",
        headers=headers,
        json={"text": "Edited workspace segment text for verification."},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["is_user_edited"] is True
    assert "Edited workspace" in patched.json()["text"]

    renamed = client.post(
        f"/api/v1/meetings/{meeting_id}/speakers/rename",
        headers=headers,
        json={"speaker_label": label, "display_name": "Alex"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["updated_segments"] >= 1

    refreshed = client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=headers)
    assert refreshed.status_code == 200
    first = next(row for row in refreshed.json()["items"] if row["id"] == segment_id)
    assert first["speaker"]["display_name"] == "Alex"

    md_export = client.post(
        f"/api/v1/meetings/{meeting_id}/exports",
        headers=headers,
        json={"format": "markdown", "include_transcript": True},
    )
    assert md_export.status_code == 200, md_export.text
    md_body = md_export.json()
    assert md_body["format"] == "markdown"
    assert md_body["filename"].endswith(".md")
    assert "Alex" in md_body["content"] or "Edited workspace" in md_body["content"]

    json_export = client.post(
        f"/api/v1/meetings/{meeting_id}/exports",
        headers=headers,
        json={"format": "json", "include_transcript": True},
    )
    assert json_export.status_code == 200, json_export.text
    assert json_export.json()["content_type"] == "application/json"
    assert '"title"' in json_export.json()["content"]

    recordings = client.get(f"/api/v1/meetings/{meeting_id}/recordings", headers=headers)
    assert recordings.status_code == 200
    assert len(recordings.json()) >= 1

    meeting_storage = Path(__file__).resolve().parent / "_audio_tmp" / "meetings" / meeting_id
    audio_files = [p for p in meeting_storage.rglob("*") if p.is_file()]
    assert audio_files, "expected local audio file before delete"

    page = client.get(f"/meetings/{meeting_id}")
    assert page.status_code == 200
    assert b"meeting.js" in page.content

    deleted = client.delete(f"/api/v1/meetings/{meeting_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert not any(p.exists() for p in audio_files)

    missing = client.get(f"/api/v1/meetings/{meeting_id}", headers=headers)
    assert missing.status_code == 404


def test_delete_forever_removes_row_audio_embeddings_and_shares(client: TestClient) -> None:
    headers = bearer_for(client, "delete-forever@example.com")
    meeting_id = _ready_meeting(client, headers)
    meeting_uuid = UUID(meeting_id)

    share = client.post(
        f"/api/v1/meetings/{meeting_id}/share-links",
        headers=headers,
        json={},
    )
    assert share.status_code in {200, 201}, share.text
    token = share.json()["token"]
    assert client.get(f"/api/v1/share/{token}").status_code == 200

    session = get_session_factory()()
    try:
        chunk_count = session.scalar(
            select(func.count())
            .select_from(TranscriptChunk)
            .where(TranscriptChunk.meeting_id == meeting_uuid)
        )
        share_count = session.scalar(
            select(func.count())
            .select_from(MeetingShareLink)
            .where(MeetingShareLink.meeting_id == meeting_uuid)
        )
        meeting_row = session.get(Meeting, meeting_uuid)
    finally:
        session.close()
    assert chunk_count and chunk_count > 0
    assert share_count == 1
    assert meeting_row is not None

    meeting_storage = Path(__file__).resolve().parent / "_audio_tmp" / "meetings" / meeting_id
    audio_files = [p for p in meeting_storage.rglob("*") if p.is_file()]
    assert audio_files, "expected local audio file before delete"

    deleted = client.delete(f"/api/v1/meetings/{meeting_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text

    # 1) meeting row gone
    assert client.get(f"/api/v1/meetings/{meeting_id}", headers=headers).status_code == 404
    session = get_session_factory()()
    try:
        assert session.get(Meeting, meeting_uuid) is None
        # 2) embeddings/chunks gone
        assert (
            session.scalar(
                select(func.count())
                .select_from(TranscriptChunk)
                .where(TranscriptChunk.meeting_id == meeting_uuid)
            )
            == 0
        )
        # 3) share links revoked / gone
        assert (
            session.scalar(
                select(func.count())
                .select_from(MeetingShareLink)
                .where(MeetingShareLink.meeting_id == meeting_uuid)
            )
            == 0
        )
    finally:
        session.close()

    # 4) audio object gone from storage
    assert not any(p.exists() for p in audio_files)
    assert client.get(f"/api/v1/share/{token}").status_code == 404
