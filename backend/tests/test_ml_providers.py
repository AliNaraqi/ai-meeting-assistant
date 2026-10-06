from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.prompts.extraction import PROMPT_VERSION, format_ms
from app.schemas.intelligence import EvidenceRef, FollowUpEmail, KeyPoint, MeetingIntelligence
from app.schemas.transcript import MeetingMetadata, TranscriptSegment
from app.services.embeddings import MockEmbeddingProvider
from app.services.evidence import validate_meeting_intelligence
from app.services.meeting_intelligence import (
    MeetingIntelligenceError,
    MockMeetingIntelligenceProvider,
)
from app.services.providers import (
    get_embedding_provider,
    get_meeting_intelligence_provider,
    get_transcription_provider,
)
from app.services.transcription import MockTranscriptionProvider


@pytest.mark.asyncio
async def test_mock_transcription_creates_segments(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF....WAVE")

    provider = MockTranscriptionProvider()
    result = await provider.transcribe(
        audio,
        language="en",
        diarize=True,
        prompt_context=None,
    )

    assert result.provider == "mock"
    assert len(result.segments) == 4
    assert result.segments[0].speaker_label == "speaker_0"
    assert result.segments[1].speaker_label == "speaker_1"
    assert result.duration_ms == result.segments[-1].end_ms


@pytest.mark.asyncio
async def test_mock_transcription_missing_file(tmp_path: Path) -> None:
    provider = MockTranscriptionProvider()
    with pytest.raises(FileNotFoundError):
        await provider.transcribe(
            tmp_path / "missing.wav",
            language="en",
            diarize=False,
            prompt_context=None,
        )


@pytest.mark.asyncio
async def test_mock_intelligence_extracts_actions_and_decisions() -> None:
    segments = [
        TranscriptSegment(
            id=uuid4(),
            ordinal=0,
            speaker_label="speaker_0",
            start_ms=0,
            end_ms=3000,
            text="Thanks everyone. Let us review the data migration first.",
        ),
        TranscriptSegment(
            id=uuid4(),
            ordinal=1,
            speaker_label="speaker_1",
            start_ms=3100,
            end_ms=7000,
            text="I will send the revised dataset by Friday.",
        ),
        TranscriptSegment(
            id=uuid4(),
            ordinal=2,
            speaker_label="speaker_0",
            start_ms=7100,
            end_ms=10000,
            text="Should we use Azure for the staging environment?",
        ),
        TranscriptSegment(
            id=uuid4(),
            ordinal=3,
            speaker_label="speaker_1",
            start_ms=10100,
            end_ms=13000,
            text="We decided to use Azure for staging.",
        ),
    ]
    metadata = MeetingMetadata(
        title="Project Aurora weekly sync",
        meeting_type="standup",
        participant_aliases=["Mina", "Noah"],
    )
    provider = MockMeetingIntelligenceProvider()
    result = await provider.extract(metadata, segments, template="standup")

    assert result.schema_version == "1.0"
    assert len(result.action_items) == 1
    assert result.action_items[0].due_date_text == "Friday"
    assert result.action_items[0].owner is None
    assert len(result.decisions) == 1
    assert result.questions[0].status == "answered"
    assert provider.prompt_version == PROMPT_VERSION

    issues = validate_meeting_intelligence(result, segments)
    assert issues == []


@pytest.mark.asyncio
async def test_intelligence_rejects_invalid_evidence() -> None:
    real_id = uuid4()
    fake_id = uuid4()
    segments = [
        TranscriptSegment(
            id=real_id,
            ordinal=0,
            speaker_label="speaker_0",
            start_ms=0,
            end_ms=1000,
            text="Hello",
        )
    ]
    bad = MeetingIntelligence(
        suggested_title="Bad",
        one_sentence_summary="Bad summary.",
        executive_summary="Bad executive summary.",
        key_points=[
            KeyPoint(
                text="Invented claim",
                evidence=[EvidenceRef(segment_id=fake_id)],
                confidence_label="high",
            )
        ],
        follow_up_email=FollowUpEmail(subject="Hi", body="Body"),
    )
    issues = validate_meeting_intelligence(bad, segments)
    assert any(issue.code == "invalid_evidence" for issue in issues)


@pytest.mark.asyncio
async def test_empty_transcript_raises() -> None:
    provider = MockMeetingIntelligenceProvider()
    with pytest.raises(MeetingIntelligenceError):
        await provider.extract(
            MeetingMetadata(title="Empty"),
            [],
            template="general",
        )


@pytest.mark.asyncio
async def test_mock_embeddings_are_deterministic() -> None:
    provider = MockEmbeddingProvider(dimensions=8)
    a = await provider.embed(["hello world"])
    b = await provider.embed(["hello world"])
    c = await provider.embed(["different text"])
    assert a == b
    assert a != c
    assert len(a[0]) == 8


def test_format_ms() -> None:
    assert format_ms(0) == "00:00"
    assert format_ms(65_000) == "01:05"
    assert format_ms(3_661_000) == "01:01:01"


def test_provider_factories_return_mocks() -> None:
    assert isinstance(get_transcription_provider(), MockTranscriptionProvider)
    assert isinstance(get_meeting_intelligence_provider(), MockMeetingIntelligenceProvider)
    assert isinstance(get_embedding_provider(), MockEmbeddingProvider)


def test_provider_factories_select_openai_when_key_set(monkeypatch: object) -> None:
    from app.config import get_settings
    from app.services.embeddings import OpenAIEmbeddingProvider
    from app.services.meeting_intelligence import OpenAIMeetingIntelligenceProvider
    from app.services.providers import get_qa_provider, log_provider_mode
    from app.services.qa import OpenAIQAProvider
    from app.services.transcription import OpenAITranscriptionProvider

    get_settings.cache_clear()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")  # type: ignore[attr-defined]
    get_settings.cache_clear()
    assert isinstance(get_transcription_provider(), OpenAITranscriptionProvider)
    assert isinstance(get_meeting_intelligence_provider(), OpenAIMeetingIntelligenceProvider)
    assert isinstance(get_embedding_provider(), OpenAIEmbeddingProvider)
    assert isinstance(get_qa_provider(), OpenAIQAProvider)
    assert log_provider_mode() == "openai"
    get_settings.cache_clear()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # type: ignore[attr-defined]
    get_settings.cache_clear()
