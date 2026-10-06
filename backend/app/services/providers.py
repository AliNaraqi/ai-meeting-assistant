"""Factory helpers for ML providers (mock vs OpenAI via OPENAI_API_KEY)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import get_settings
from app.services.embeddings import (
    EmbeddingProvider,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from app.services.meeting_intelligence import (
    MeetingIntelligenceProvider,
    MockMeetingIntelligenceProvider,
    OpenAIMeetingIntelligenceProvider,
)
from app.services.transcription import (
    MockTranscriptionProvider,
    OpenAITranscriptionProvider,
    TranscriptionProvider,
)

if TYPE_CHECKING:
    from app.services.qa import QAProvider

logger = logging.getLogger(__name__)


def openai_enabled() -> bool:
    return bool(get_settings().openai_api_key.strip())


def get_transcription_provider() -> TranscriptionProvider:
    if openai_enabled():
        return OpenAITranscriptionProvider()
    return MockTranscriptionProvider()


def get_meeting_intelligence_provider() -> MeetingIntelligenceProvider:
    if openai_enabled():
        return OpenAIMeetingIntelligenceProvider()
    return MockMeetingIntelligenceProvider()


def get_embedding_provider() -> EmbeddingProvider:
    if openai_enabled():
        return OpenAIEmbeddingProvider()
    return MockEmbeddingProvider()


def get_qa_provider() -> QAProvider:
    # Lazy import avoids providers ↔ qa ↔ indexing circular dependency.
    from app.services.qa import MockQAProvider, OpenAIQAProvider

    if openai_enabled():
        return OpenAIQAProvider()
    return MockQAProvider()


def log_provider_mode() -> str:
    """Log and return the active provider mode (openai | mock)."""
    mode = "openai" if openai_enabled() else "mock"
    logger.info("AI provider mode: %s", mode)
    return mode
