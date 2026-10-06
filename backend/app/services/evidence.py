"""Validate AI outputs against transcript evidence and safety rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from app.schemas.intelligence import MeetingIntelligence
from app.schemas.transcript import TranscriptSegment

_HTML_RE = re.compile(r"<[^>]+>")
_MAX_TAG_LEN = 40
_MAX_TAGS = 20
_MAX_SUMMARY_CHARS = 8_000


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


def _segment_index(segments: list[TranscriptSegment]) -> dict[UUID, TranscriptSegment]:
    return {segment.id: segment for segment in segments}


def _has_html(*values: str | None) -> bool:
    return any(value is not None and _HTML_RE.search(value) for value in values)


def validate_meeting_intelligence(
    intelligence: MeetingIntelligence,
    segments: list[TranscriptSegment],
    *,
    meeting_date: date | None = None,
) -> list[ValidationIssue]:
    """Return validation issues. Empty list means the payload is safe to store."""
    issues: list[ValidationIssue] = []
    known = _segment_index(segments)
    ordinal_by_id = {segment.id: segment.ordinal for segment in segments}

    if _has_html(
        intelligence.suggested_title,
        intelligence.one_sentence_summary,
        intelligence.executive_summary,
        intelligence.follow_up_email.subject,
        intelligence.follow_up_email.body,
    ):
        issues.append(ValidationIssue("unexpected_html", "Output contains HTML markup."))

    if len(intelligence.executive_summary) > _MAX_SUMMARY_CHARS:
        issues.append(ValidationIssue("output_too_large", "Executive summary exceeds size bound."))

    if len(intelligence.tags) > _MAX_TAGS:
        issues.append(ValidationIssue("too_many_tags", f"At most {_MAX_TAGS} tags allowed."))

    for tag in intelligence.tags:
        if not tag.strip() or len(tag) > _MAX_TAG_LEN:
            issues.append(ValidationIssue("invalid_tag", f"Invalid tag: {tag!r}"))

    def check_evidence(label: str, evidence_ids: list[UUID]) -> None:
        if not evidence_ids:
            issues.append(ValidationIssue("empty_evidence", f"{label} has no evidence."))
            return
        for segment_id in evidence_ids:
            if segment_id not in known:
                issues.append(
                    ValidationIssue(
                        "invalid_evidence",
                        f"{label} cites unknown segment {segment_id}.",
                    )
                )

    for key_point in intelligence.key_points:
        check_evidence("key_point", [ref.segment_id for ref in key_point.evidence])
        if _has_html(key_point.text):
            issues.append(ValidationIssue("unexpected_html", "Key point contains HTML."))

    for decision in intelligence.decisions:
        check_evidence("decision", [ref.segment_id for ref in decision.evidence])
        if _has_html(decision.text, decision.made_by):
            issues.append(ValidationIssue("unexpected_html", "Decision contains HTML."))

    for action in intelligence.action_items:
        check_evidence("action_item", [ref.segment_id for ref in action.evidence])
        if _has_html(action.task, action.owner, action.due_date_text):
            issues.append(ValidationIssue("unexpected_html", "Action item contains HTML."))
        if action.due_date is not None and meeting_date is not None:
            if action.due_date < meeting_date - timedelta(days=1):
                issues.append(
                    ValidationIssue(
                        "implausible_due_date",
                        f"Action due date {action.due_date} precedes meeting date.",
                    )
                )

    for question in intelligence.questions:
        check_evidence("question", [ref.segment_id for ref in question.evidence])
        if _has_html(question.question, question.answer, question.owner):
            issues.append(ValidationIssue("unexpected_html", "Question contains HTML."))

    for risk in intelligence.risks:
        check_evidence("risk", [ref.segment_id for ref in risk.evidence])
        if _has_html(risk.text, risk.mitigation):
            issues.append(ValidationIssue("unexpected_html", "Risk contains HTML."))

    for topic in intelligence.topics:
        if topic.start_segment_id not in known or topic.end_segment_id not in known:
            issues.append(
                ValidationIssue(
                    "invalid_topic_boundary",
                    f"Topic {topic.name!r} has invalid segment boundaries.",
                )
            )
            continue
        if ordinal_by_id[topic.start_segment_id] > ordinal_by_id[topic.end_segment_id]:
            issues.append(
                ValidationIssue(
                    "invalid_topic_order",
                    f"Topic {topic.name!r} start ordinal is after end ordinal.",
                )
            )
        if _has_html(topic.name, topic.summary):
            issues.append(ValidationIssue("unexpected_html", "Topic contains HTML."))

    return issues
