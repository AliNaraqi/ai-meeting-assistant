"""Meeting export helpers (Markdown, JSON, Slack, Notion, actions CSV)."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ActionItemRow,
    MeetingInsight,
    Participant,
    TranscriptSegmentRow,
    User,
)
from app.services import meetings as meeting_service
from app.services.transcript import speaker_display_map

ExportFormat = Literal["markdown", "json", "slack", "notion", "actions_csv"]


def build_export(
    db: Session,
    owner: User,
    meeting_id: UUID,
    *,
    fmt: ExportFormat,
    include_transcript: bool,
    include_participant_emails: bool,
) -> dict[str, Any]:
    meeting = meeting_service.get_owned_meeting(db, owner, meeting_id)
    insight = db.scalar(
        select(MeetingInsight)
        .where(MeetingInsight.meeting_id == meeting.id)
        .order_by(MeetingInsight.version.desc())
        .limit(1)
    )
    actions = list(
        db.scalars(
            select(ActionItemRow)
            .where(ActionItemRow.meeting_id == meeting.id)
            .order_by(ActionItemRow.created_at.asc())
        ).all()
    )
    participants = list(
        db.scalars(select(Participant).where(Participant.meeting_id == meeting.id)).all()
    )
    segments = list(
        db.scalars(
            select(TranscriptSegmentRow)
            .where(TranscriptSegmentRow.meeting_id == meeting.id)
            .order_by(TranscriptSegmentRow.ordinal.asc())
        ).all()
    )
    displays = speaker_display_map(db, meeting.id)

    payload: dict[str, Any] = {
        "id": str(meeting.id),
        "title": meeting.title,
        "status": meeting.status,
        "meeting_type": meeting.meeting_type,
        "language": meeting.language,
        "location": meeting.location,
        "occurred_at": meeting.occurred_at.isoformat() if meeting.occurred_at else None,
        "exported_at": datetime.now(UTC).isoformat(),
        "participants": [
            {
                "display_name": p.display_name,
                "role": p.role,
                "speaker_label": p.speaker_label,
                **(
                    {"email": p.email}
                    if include_participant_emails and p.email
                    else {}
                ),
            }
            for p in participants
        ],
        "insights": None
        if insight is None
        else {
            "version": insight.version,
            "one_sentence_summary": insight.one_sentence_summary,
            "executive_summary": insight.executive_summary,
            "key_points": insight.key_points,
            "decisions": insight.decisions,
            "questions": insight.questions,
            "risks": insight.risks,
            "topics": insight.topics,
            "tags": insight.tags,
            "follow_up_email": insight.follow_up_email,
        },
        "actions": [
            {
                "task": a.task,
                "owner_text": a.owner_text,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "due_date_text": a.due_date_text,
                "status": a.status,
                "priority": a.priority,
                "evidence_segment_ids": a.evidence_segment_ids,
            }
            for a in actions
        ],
    }
    if include_transcript:
        payload["transcript"] = [
            {
                "ordinal": s.ordinal,
                "speaker_label": s.speaker_label,
                "display_name": displays.get(s.speaker_label),
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "text": s.text,
            }
            for s in segments
        ]

    export_id = str(uuid4())
    filename_stem = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in meeting.title)[
        :60
    ] or "meeting"

    if fmt == "json":
        return {
            "id": export_id,
            "format": "json",
            "status": "ready",
            "filename": f"{filename_stem}.json",
            "content": json.dumps(payload, indent=2, ensure_ascii=False),
            "content_type": "application/json",
        }

    if fmt == "markdown":
        return {
            "id": export_id,
            "format": "markdown",
            "status": "ready",
            "filename": f"{filename_stem}.md",
            "content": _to_markdown(payload, include_transcript=include_transcript),
            "content_type": "text/markdown; charset=utf-8",
        }

    if fmt == "slack":
        return {
            "id": export_id,
            "format": "slack",
            "status": "ready",
            "filename": f"{filename_stem}-slack.txt",
            "content": _to_slack(payload),
            "content_type": "text/plain; charset=utf-8",
        }

    if fmt == "notion":
        return {
            "id": export_id,
            "format": "notion",
            "status": "ready",
            "filename": f"{filename_stem}-notion.md",
            "content": _to_notion(payload, include_transcript=include_transcript),
            "content_type": "text/markdown; charset=utf-8",
        }

    if fmt == "actions_csv":
        return {
            "id": export_id,
            "format": "actions_csv",
            "status": "ready",
            "filename": f"{filename_stem}-actions.csv",
            "content": _to_actions_csv(payload),
            "content_type": "text/csv; charset=utf-8",
        }

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": {"code": "validation_error", "message": "Unsupported export format."}},
    )


def _fmt_ms(ms: int) -> str:
    total = max(0, ms // 1000)
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _to_markdown(payload: dict[str, Any], *, include_transcript: bool) -> str:
    lines: list[str] = [
        f"# {payload['title']}",
        "",
        f"- Status: `{payload['status']}`",
        f"- Type: `{payload['meeting_type']}`",
    ]
    if payload.get("location"):
        lines.append(f"- Location: {payload['location']}")
    if payload.get("occurred_at"):
        lines.append(f"- Occurred: {payload['occurred_at']}")
    lines.append(f"- Exported: {payload['exported_at']}")
    lines.append("")

    if payload["participants"]:
        lines.extend(["## Participants", ""])
        for person in payload["participants"]:
            role = f" ({person['role']})" if person.get("role") else ""
            lines.append(f"- {person['display_name']}{role}")
        lines.append("")

    insights = payload.get("insights")
    if insights:
        lines.extend(
            [
                "## Summary",
                "",
                insights["one_sentence_summary"],
                "",
                insights["executive_summary"],
                "",
                "## Decisions",
                "",
            ]
        )
        if insights["decisions"]:
            for item in insights["decisions"]:
                lines.append(f"- {item.get('text', '')}")
        else:
            lines.append("- None captured.")
        lines.append("")

    lines.extend(["## Actions", ""])
    if payload["actions"]:
        for action in payload["actions"]:
            owner = f" (owner: {action['owner_text']})" if action.get("owner_text") else ""
            due = f" due {action['due_date_text']}" if action.get("due_date_text") else ""
            lines.append(f"- [{action['status']}] {action['task']}{owner}{due}")
    else:
        lines.append("- None captured.")
    lines.append("")

    if include_transcript and payload.get("transcript"):
        lines.extend(["## Transcript", ""])
        for segment in payload["transcript"]:
            speaker = segment.get("display_name") or segment["speaker_label"]
            lines.append(f"**[{_fmt_ms(segment['start_ms'])}] {speaker}:** {segment['text']}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _to_slack(payload: dict[str, Any]) -> str:
    lines = [f"*{payload['title']}*", ""]
    insights = payload.get("insights")
    if insights:
        lines.append(insights["one_sentence_summary"])
        lines.append("")
    lines.append("*Decisions*")
    decisions = (insights or {}).get("decisions") or []
    if decisions:
        for item in decisions:
            lines.append(f"• {item.get('text', '')}")
    else:
        lines.append("• None captured")
    lines.append("")
    lines.append("*Actions*")
    if payload["actions"]:
        for action in payload["actions"]:
            owner = f" — {action['owner_text']}" if action.get("owner_text") else ""
            due = f" (due {action['due_date_text']})" if action.get("due_date_text") else ""
            lines.append(f"• [{action['status']}] {action['task']}{owner}{due}")
    else:
        lines.append("• None captured")
    lines.append("")
    return "\n".join(lines)


def _to_notion(payload: dict[str, Any], *, include_transcript: bool) -> str:
    base = _to_markdown(payload, include_transcript=include_transcript)
    header = (
        f"> 📌 Imported from AI Meeting Assistant on {payload['exported_at']}\n\n"
        f"> Template hint: `{payload['meeting_type']}`\n\n"
    )
    return header + base


def _to_actions_csv(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["task", "owner", "due", "status", "priority", "meeting_title"],
    )
    writer.writeheader()
    for action in payload["actions"]:
        writer.writerow(
            {
                "task": action["task"],
                "owner": action.get("owner_text") or "",
                "due": action.get("due_date") or action.get("due_date_text") or "",
                "status": action["status"],
                "priority": action.get("priority") or "",
                "meeting_title": payload["title"],
            }
        )
    return buffer.getvalue()
