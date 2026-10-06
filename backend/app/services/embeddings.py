"""Embedding provider interface, mock, and OpenAI implementation."""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class MockEmbeddingProvider:
    """Deterministic pseudo-embeddings for tests (fixed dimension, no API)."""

    def __init__(self, dimensions: int = 8, model_name: str = "mock-embed-v1") -> None:
        if dimensions < 2:
            raise ValueError("dimensions must be >= 2")
        self.dimensions = dimensions
        self.model_name = model_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [b / 255.0 for b in digest[: self.dimensions]]
        norm = sum(v * v for v in values) ** 0.5 or 1.0
        return [v / norm for v in values]


class OpenAIEmbeddingProvider:
    """OpenAI embeddings using text-embedding-3-small by default."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIEmbeddingProvider")
        self.model_name = self.settings.openai_embedding_model.strip() or "text-embedding-3-small"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        try:
            response = await client.embeddings.create(
                model=self.model_name,
                input=texts,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenAI embeddings failed")
            raise RuntimeError(f"OpenAI embeddings failed: {exc}") from exc

        # API returns data ordered by index.
        ordered = sorted(response.data, key=lambda row: row.index)
        return [list(row.embedding) for row in ordered]
