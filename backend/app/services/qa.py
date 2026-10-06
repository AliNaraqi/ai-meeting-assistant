"""Grounded meeting Q&A with citation validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ChatMessage, ChatRole, TranscriptChunk, TranscriptSegmentRow, User
from app.prompts.qa import PROMPT_VERSION, QA_SYSTEM_PROMPT, build_qa_user_prompt
from app.schemas.qa import AnswerResponse, ChatMessageOut, CitationOut
from app.services import indexing as indexing_service
from app.services import meetings as meeting_service
from app.services import quotas as quota_service
from app.services.quotas import estimate_tokens
from app.services.transcript import speaker_display_map

AnswerStatus = Literal["supported", "partially_supported", "not_found"]

_WORD_RE = re.compile(r"[a-z0-9]+")
_INJECTION_RE = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior)\s+instructions|system\s*prompt|reveal\s+secret)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContextSegment:
    id: UUID
    start_ms: int
    end_ms: int
    speaker_label: str
    speaker_name: str
    text: str


@dataclass(frozen=True)
class MeetingAnswer:
    answer: str
    answer_status: AnswerStatus
    citations: list[UUID]
    model_name: str


class QAProvider(Protocol):
    async def answer(
        self,
        question: str,
        context: list[ContextSegment],
    ) -> MeetingAnswer: ...


class MockQAProvider:
    """Deterministic grounded answers for CI — never calls an external API."""

    def __init__(self, model_name: str = "mock-qa-v1") -> None:
        self.model_name = model_name
        self.prompt_version = PROMPT_VERSION
        self.system_prompt = QA_SYSTEM_PROMPT

    async def answer(
        self,
        question: str,
        context: list[ContextSegment],
    ) -> MeetingAnswer:
        _ = build_qa_user_prompt(
            question,
            "\n".join(f"{item.id}: {item.text}" for item in context),
        )
        if not context:
            return MeetingAnswer(
                answer="The meeting transcript does not establish an answer to that question.",
                answer_status="not_found",
                citations=[],
                model_name=self.model_name,
            )

        # Treat transcript text as untrusted; never follow embedded instructions.
        clean_context = [
            item
            for item in context
            if not _INJECTION_RE.search(item.text)
        ] or context

        q = question.lower()
        dataset_hit = next(
            (
                item
                for item in clean_context
                if "dataset" in item.text.lower() and "friday" in item.text.lower()
            ),
            None,
        )
        azure_hit = next(
            (item for item in clean_context if "azure" in item.text.lower()),
            None,
        )

        if (
            any(token in q for token in ("dataset", "friday", "owns", "owner", "send"))
            and dataset_hit
        ):
            return MeetingAnswer(
                answer="A speaker said they will send the revised dataset by Friday.",
                answer_status="supported",
                citations=[dataset_hit.id],
                model_name=self.model_name,
            )

        if (
            any(token in q for token in ("azure", "cloud", "staging", "provider", "decided"))
            and azure_hit
        ):
            return MeetingAnswer(
                answer="The team decided to use Azure for staging.",
                answer_status="supported",
                citations=[azure_hit.id],
                model_name=self.model_name,
            )

        # Fallback: lexical overlap with clean context only.
        stop = {"the", "a", "an", "to", "of", "and", "or", "what", "who", "when", "did"}
        q_tokens = set(_WORD_RE.findall(q)) - stop
        best: ContextSegment | None = None
        best_score = 0
        for item in clean_context:
            tokens = set(_WORD_RE.findall(item.text.lower()))
            score = len(q_tokens & tokens)
            if score > best_score:
                best = item
                best_score = score

        if best is None or best_score < 2:
            return MeetingAnswer(
                answer="The meeting transcript does not establish an answer to that question.",
                answer_status="not_found",
                citations=[],
                model_name=self.model_name,
            )

        return MeetingAnswer(
            answer=f"From the transcript: {best.text}",
            answer_status="partially_supported",
            citations=[best.id],
            model_name=self.model_name,
        )


class OpenAIQAProvider:
    """OpenAI Responses API grounded Q&A with structured MeetingAnswer schema."""

    def __init__(self, settings: object | None = None) -> None:
        from app.config import Settings, get_settings

        self.settings: Settings = settings if isinstance(settings, Settings) else get_settings()
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIQAProvider")
        self.model_name = self.settings.openai_qa_model.strip() or "gpt-4o-mini"
        self.prompt_version = PROMPT_VERSION
        self.system_prompt = QA_SYSTEM_PROMPT

    async def answer(
        self,
        question: str,
        context: list[ContextSegment],
    ) -> MeetingAnswer:
        from openai import AsyncOpenAI

        from app.schemas.intelligence import MeetingAnswer as StructuredMeetingAnswer

        if not context:
            return MeetingAnswer(
                answer="The meeting transcript does not establish an answer to that question.",
                answer_status="not_found",
                citations=[],
                model_name=self.model_name,
            )

        context_block = "\n".join(
            f"[segment_id={item.id} start_ms={item.start_ms} speaker={item.speaker_name}] "
            f"{item.text}"
            for item in context
        )
        user_prompt = build_qa_user_prompt(question, context_block)
        client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        try:
            response = await client.responses.parse(
                model=self.model_name,
                input=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=StructuredMeetingAnswer,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OpenAI Q&A failed: {exc}") from exc

        parsed = response.output_parsed
        if parsed is None:
            return MeetingAnswer(
                answer="The meeting transcript does not establish an answer to that question.",
                answer_status="not_found",
                citations=[],
                model_name=self.model_name,
            )
        return MeetingAnswer(
            answer=parsed.answer,
            answer_status=parsed.answer_status,
            citations=[citation.segment_id for citation in parsed.citations],
            model_name=self.model_name,
        )


def _segments_for_chunks(
    db: Session,
    meeting_id: UUID,
    chunks: list[TranscriptChunk],
) -> list[ContextSegment]:
    if not chunks:
        return []
    segment_ids: set[UUID] = set()
    for chunk in chunks:
        # Expand to all segments whose IDs appear in chunk content labels, via ordinal range.
        rows = list(
            db.scalars(
                select(TranscriptSegmentRow)
                .where(
                    TranscriptSegmentRow.meeting_id == meeting_id,
                    TranscriptSegmentRow.start_ms >= chunk.start_ms,
                    TranscriptSegmentRow.end_ms <= chunk.end_ms,
                )
                .order_by(TranscriptSegmentRow.ordinal.asc())
            ).all()
        )
        for row in rows:
            segment_ids.add(row.id)

    # Also include first/last explicitly in case of timing edge cases.
    for chunk in chunks:
        segment_ids.add(chunk.first_segment_id)
        segment_ids.add(chunk.last_segment_id)

    rows = list(
        db.scalars(
            select(TranscriptSegmentRow)
            .where(
                TranscriptSegmentRow.meeting_id == meeting_id,
                TranscriptSegmentRow.id.in_(segment_ids),
            )
            .order_by(TranscriptSegmentRow.ordinal.asc())
        ).all()
    )
    displays = speaker_display_map(db, meeting_id)
    return [
        ContextSegment(
            id=row.id,
            start_ms=row.start_ms,
            end_ms=row.end_ms,
            speaker_label=row.speaker_label,
            speaker_name=displays.get(row.speaker_label) or row.speaker_label,
            text=row.text,
        )
        for row in rows
    ]


def _validate_citations(
    citations: list[UUID],
    context: list[ContextSegment],
) -> list[UUID]:
    allowed = {item.id for item in context}
    return [cid for cid in citations if cid in allowed]


def ask_question(
    db: Session,
    owner: User,
    meeting_id: UUID,
    question: str,
) -> AnswerResponse:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    cleaned = question.strip()
    settings = get_settings()
    chunks = indexing_service.retrieve_chunks(db, meeting_id, question=cleaned, top_k=3)
    context = _segments_for_chunks(db, meeting_id, chunks)

    estimated = (
        estimate_tokens(cleaned, *(item.text for item in context), *(chunk.content for chunk in chunks))
        + 800
    )
    quota_service.enforce_llm_token_quota(
        db, owner, settings, additional_tokens=estimated, as_http=True
    )

    import asyncio

    from app.services.providers import get_qa_provider

    raw = asyncio.run(get_qa_provider().answer(cleaned, context))
    valid_ids = _validate_citations(raw.citations, context)
    context_by_id = {item.id: item for item in context}

    if raw.answer_status != "not_found" and not valid_ids:
        answer = "The meeting transcript does not establish an answer to that question."
        status: AnswerStatus = "not_found"
        citations: list[CitationOut] = []
    else:
        answer = raw.answer
        status = raw.answer_status if valid_ids or raw.answer_status == "not_found" else "not_found"
        if status == "not_found":
            citations = []
            answer = "The meeting transcript does not establish an answer to that question."
        else:
            citations = [
                CitationOut(
                    segment_id=cid,
                    start_ms=context_by_id[cid].start_ms,
                    speaker_name=context_by_id[cid].speaker_name,
                    text=context_by_id[cid].text,
                )
                for cid in valid_ids
            ]

    used = estimated + estimate_tokens(answer)
    quota_service.record_llm_tokens(db, owner.id, tokens=used)

    db.add(
        ChatMessage(
            meeting_id=meeting_id,
            user_id=owner.id,
            role=ChatRole.user.value,
            content=cleaned,
            citations=[],
        )
    )
    db.add(
        ChatMessage(
            meeting_id=meeting_id,
            user_id=owner.id,
            role=ChatRole.assistant.value,
            content=answer,
            citations=[c.model_dump(mode="json") for c in citations],
            answer_status=status,
            model_name=raw.model_name,
        )
    )
    db.flush()

    return AnswerResponse(
        answer=answer,
        answer_status=status,
        citations=citations,
        model_name=raw.model_name,
    )


def list_chat(
    db: Session,
    owner: User,
    meeting_id: UUID,
    *,
    limit: int = 100,
) -> list[ChatMessageOut]:
    meeting_service.get_owned_meeting(db, owner, meeting_id)
    rows = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.meeting_id == meeting_id, ChatMessage.user_id == owner.id)
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
        ).all()
    )
    items: list[ChatMessageOut] = []
    for row in rows:
        citations = [
            CitationOut.model_validate(item)
            for item in (row.citations or [])
            if isinstance(item, dict)
        ]
        items.append(
            ChatMessageOut(
                id=row.id,
                role=row.role if row.role in {"user", "assistant"} else "assistant",
                content=row.content,
                citations=citations,
                answer_status=row.answer_status,
                model_name=row.model_name,
                created_at=row.created_at,
            )
        )
    return items
