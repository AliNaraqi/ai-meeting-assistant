"""Meeting intelligence extraction provider interface and mock."""

from __future__ import annotations

from typing import Protocol

from app.config import Settings, get_settings
from app.prompts.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_extraction_user_prompt,
    segment_block,
)
from app.schemas.intelligence import (
    ActionItem,
    Decision,
    EvidenceRef,
    FollowUpEmail,
    KeyPoint,
    MeetingIntelligence,
    Question,
    Topic,
)
from app.schemas.transcript import MeetingMetadata, TranscriptSegment
from app.services.evidence import ValidationIssue, validate_meeting_intelligence


class MeetingIntelligenceError(RuntimeError):
    def __init__(self, message: str, issues: list[ValidationIssue] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


class MeetingIntelligenceProvider(Protocol):
    async def extract(
        self,
        metadata: MeetingMetadata,
        segments: list[TranscriptSegment],
        template: str,
    ) -> MeetingIntelligence: ...


class MockMeetingIntelligenceProvider:
    """Rule-based extractor for demos/tests — no LLM API calls."""

    def __init__(
        self,
        *,
        enforce_validation: bool = True,
        model_name: str = "mock-meeting-intelligence",
    ) -> None:
        self.enforce_validation = enforce_validation
        self.prompt_version = PROMPT_VERSION
        self.model_name = model_name

    def build_prompts(
        self,
        metadata: MeetingMetadata,
        segments: list[TranscriptSegment],
        template: str,
    ) -> tuple[str, str]:
        blocks = [
            segment_block(
                segment_id=str(segment.id),
                start_ms=segment.start_ms,
                speaker=segment.speaker_display_name or segment.speaker_label,
                text=segment.text,
            )
            for segment in segments
        ]
        user_prompt = build_extraction_user_prompt(
            title=metadata.title,
            occurred_at=metadata.occurred_at.isoformat() if metadata.occurred_at else "unknown",
            meeting_type=metadata.meeting_type,
            language=metadata.language or "en",
            participant_aliases=metadata.participant_aliases,
            transcript_blocks=blocks,
            template=template,
        )
        return EXTRACTION_SYSTEM_PROMPT, user_prompt

    async def extract(
        self,
        metadata: MeetingMetadata,
        segments: list[TranscriptSegment],
        template: str,
    ) -> MeetingIntelligence:
        if not segments:
            raise MeetingIntelligenceError("Cannot extract insights from an empty transcript.")

        # Touch prompts so callers/tests can assert grounding contract is wired.
        _system, _user = self.build_prompts(metadata, segments, template)

        first = segments[0]
        last = segments[-1]

        action_seg = next(
            (s for s in segments if "will send" in s.text.lower() or "i will" in s.text.lower()),
            None,
        )
        decision_seg = next((s for s in segments if "we decided" in s.text.lower()), None)
        question_seg = next((s for s in segments if "?" in s.text), None)

        action_items: list[ActionItem] = []
        if action_seg is not None:
            action_items.append(
                ActionItem(
                    task="Send the revised dataset",
                    owner=None,
                    due_date=None,
                    due_date_text="Friday" if "friday" in action_seg.text.lower() else None,
                    evidence=[EvidenceRef(segment_id=action_seg.id)],
                    confidence_label="high",
                )
            )

        decisions: list[Decision] = []
        if decision_seg is not None:
            decisions.append(
                Decision(
                    text=decision_seg.text.rstrip("."),
                    made_by=None,
                    evidence=[EvidenceRef(segment_id=decision_seg.id)],
                    confidence_label="high",
                )
            )

        questions: list[Question] = []
        if question_seg is not None:
            answered = decision_seg is not None
            questions.append(
                Question(
                    question=question_seg.text,
                    status="answered" if answered else "open",
                    answer=decision_seg.text if answered and decision_seg else None,
                    owner=None,
                    evidence=[EvidenceRef(segment_id=question_seg.id)],
                )
            )

        intelligence = MeetingIntelligence(
            suggested_title=metadata.title,
            one_sentence_summary=f"Discussion of {metadata.title.lower()} with next steps.",
            executive_summary=(
                f"The meeting covered {metadata.title}. "
                "Key commitments and decisions were captured only when explicitly stated."
            ),
            key_points=[
                KeyPoint(
                    text=first.text,
                    evidence=[EvidenceRef(segment_id=first.id)],
                    confidence_label="medium",
                )
            ],
            decisions=decisions,
            action_items=action_items,
            questions=questions,
            risks=[],
            topics=[
                Topic(
                    name=metadata.meeting_type.title(),
                    summary=f"Primary discussion spanning the meeting ({template} template).",
                    start_segment_id=first.id,
                    end_segment_id=last.id,
                )
            ],
            tags=[metadata.meeting_type, "mock"],
            follow_up_email=FollowUpEmail(
                subject=f"Follow-up: {metadata.title}",
                body=(
                    "Thanks for the discussion.\n\n"
                    "Please review the captured actions and decisions and reply with corrections."
                ),
            ),
        )

        if self.enforce_validation:
            meeting_date = metadata.occurred_at.date() if metadata.occurred_at else None
            issues = validate_meeting_intelligence(
                intelligence, segments, meeting_date=meeting_date
            )
            if issues:
                raise MeetingIntelligenceError(
                    "Extracted intelligence failed evidence validation.",
                    issues=issues,
                )

        return intelligence


class OpenAIMeetingIntelligenceProvider:
    """OpenAI Responses API + Structured Outputs for meeting intelligence."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        enforce_validation: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIMeetingIntelligenceProvider")
        self.enforce_validation = enforce_validation
        self.prompt_version = PROMPT_VERSION
        self.model_name = self.settings.openai_summary_model.strip() or "gpt-4o-mini"

    def build_prompts(
        self,
        metadata: MeetingMetadata,
        segments: list[TranscriptSegment],
        template: str,
    ) -> tuple[str, str]:
        blocks = [
            segment_block(
                segment_id=str(segment.id),
                start_ms=segment.start_ms,
                speaker=segment.speaker_display_name or segment.speaker_label,
                text=segment.text,
            )
            for segment in segments
        ]
        user_prompt = build_extraction_user_prompt(
            title=metadata.title,
            occurred_at=metadata.occurred_at.isoformat() if metadata.occurred_at else "unknown",
            meeting_type=metadata.meeting_type,
            language=metadata.language or "en",
            participant_aliases=metadata.participant_aliases,
            transcript_blocks=blocks,
            template=template,
        )
        return EXTRACTION_SYSTEM_PROMPT, user_prompt

    async def extract(
        self,
        metadata: MeetingMetadata,
        segments: list[TranscriptSegment],
        template: str,
    ) -> MeetingIntelligence:
        if not segments:
            raise MeetingIntelligenceError("Cannot extract insights from an empty transcript.")

        from openai import AsyncOpenAI

        system_prompt, user_prompt = self.build_prompts(metadata, segments, template)
        client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        try:
            response = await client.responses.parse(
                model=self.model_name,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=MeetingIntelligence,
            )
        except Exception as exc:  # noqa: BLE001
            raise MeetingIntelligenceError(f"OpenAI extraction failed: {exc}") from exc

        intelligence = response.output_parsed
        if intelligence is None:
            raise MeetingIntelligenceError("OpenAI returned no structured meeting intelligence.")

        if self.enforce_validation:
            meeting_date = metadata.occurred_at.date() if metadata.occurred_at else None
            issues = validate_meeting_intelligence(
                intelligence, segments, meeting_date=meeting_date
            )
            if issues:
                raise MeetingIntelligenceError(
                    "Extracted intelligence failed evidence validation.",
                    issues=issues,
                )
        return intelligence
