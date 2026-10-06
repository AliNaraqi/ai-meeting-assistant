"""Transcription provider interface, mock, and OpenAI implementation."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.config import Settings, get_settings
from app.schemas.transcript import NormalizedTranscript, TranscriptSegment
from app.services.audio import AudioProcessingError, split_audio_for_transcription

logger = logging.getLogger(__name__)


class TranscriptionProvider(Protocol):
    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        diarize: bool,
        prompt_context: str | None,
    ) -> NormalizedTranscript: ...


class MockTranscriptionProvider:
    """Deterministic transcript for local/CI use — never calls an external API."""

    def __init__(self, model_name: str = "mock-transcribe-v1") -> None:
        self.model_name = model_name

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        diarize: bool,
        prompt_context: str | None,
    ) -> NormalizedTranscript:
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        speakers = ["speaker_0", "speaker_1"] if diarize else ["speaker_0"]
        lines = [
            ("Thanks everyone. Let us review the data migration first.", 800, 5200),
            ("I will send the revised dataset by Friday.", 5400, 9200),
            ("Should we use Azure for the staging environment?", 9500, 12800),
            ("We decided to use Azure for staging.", 13000, 16200),
        ]

        segments: list[TranscriptSegment] = []
        for ordinal, (text, start_ms, end_ms) in enumerate(lines):
            speaker = speakers[ordinal % len(speakers)]
            segments.append(
                TranscriptSegment(
                    id=uuid4(),
                    ordinal=ordinal,
                    speaker_label=speaker,
                    speaker_display_name=f"Speaker {speakers.index(speaker) + 1}",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                    language=language or "en",
                    confidence=0.91,
                )
            )

        return NormalizedTranscript(
            segments=segments,
            language=language or "en",
            duration_ms=segments[-1].end_ms if segments else 0,
            model_name=self.model_name,
            provider="mock",
        )


class OpenAITranscriptionProvider:
    """OpenAI Audio Transcriptions API adapter."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAITranscriptionProvider")
        self.model_name = (
            self.settings.openai_transcription_model.strip() or "gpt-4o-mini-transcribe"
        )
        self.diarization_model = (
            self.settings.openai_diarization_model.strip() or "gpt-4o-transcribe-diarize"
        )

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        diarize: bool,
        prompt_context: str | None,
    ) -> NormalizedTranscript:
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        max_bytes = self.settings.transcription_max_file_bytes
        model = self.diarization_model if diarize else self.model_name

        try:
            with tempfile.TemporaryDirectory(prefix="ama-transcribe-") as tmp:
                tmp_dir = Path(tmp)
                chunks = split_audio_for_transcription(
                    audio_path,
                    tmp_dir / "chunks",
                    max_bytes=max_bytes,
                )
                all_segments: list[TranscriptSegment] = []
                detected_language = language
                for chunk_path, offset_ms in chunks:
                    part = await self._transcribe_file(
                        client,
                        chunk_path,
                        model=model,
                        language=language,
                        diarize=diarize,
                        prompt_context=prompt_context,
                        offset_ms=offset_ms,
                        start_ordinal=len(all_segments),
                    )
                    if part.language and not detected_language:
                        detected_language = part.language
                    all_segments.extend(part.segments)
        except AudioProcessingError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenAI transcription failed")
            raise RuntimeError(f"OpenAI transcription failed: {exc}") from exc

        duration_ms = all_segments[-1].end_ms if all_segments else 0
        return NormalizedTranscript(
            segments=all_segments,
            language=detected_language or language or "en",
            duration_ms=duration_ms,
            model_name=model,
            provider="openai",
        )

    async def _transcribe_file(
        self,
        client: Any,
        audio_path: Path,
        *,
        model: str,
        language: str | None,
        diarize: bool,
        prompt_context: str | None,
        offset_ms: int,
        start_ordinal: int,
    ) -> NormalizedTranscript:
        kwargs: dict[str, Any] = {
            "model": model,
            "response_format": "verbose_json",
        }
        if language:
            kwargs["language"] = language
        if prompt_context:
            kwargs["prompt"] = prompt_context[:900]
        # Segment timestamps are reliable on Whisper; newer models may omit them.
        if model.startswith("whisper"):
            kwargs["timestamp_granularities"] = ["segment"]

        with audio_path.open("rb") as handle:
            try:
                raw = await client.audio.transcriptions.create(file=handle, **kwargs)
            except Exception:
                # Some models reject verbose_json / extra kwargs — retry with JSON text.
                handle.seek(0)
                fallback = {
                    "model": model,
                    "response_format": "json",
                }
                if language:
                    fallback["language"] = language
                if prompt_context:
                    fallback["prompt"] = prompt_context[:900]
                raw = await client.audio.transcriptions.create(file=handle, **fallback)

        payload = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        text = str(payload.get("text") or "").strip()
        language_out = payload.get("language") or language
        raw_segments = payload.get("segments") or []

        segments: list[TranscriptSegment] = []
        if raw_segments:
            for index, item in enumerate(raw_segments):
                seg_text = str(item.get("text") or "").strip()
                if not seg_text:
                    continue
                start_s = float(item.get("start") or 0.0)
                end_s = float(item.get("end") or start_s)
                speaker = item.get("speaker")
                if diarize and speaker is not None:
                    label = f"speaker_{speaker}" if str(speaker).isdigit() else str(speaker)
                elif diarize:
                    label = f"speaker_{index % 2}"
                else:
                    label = "speaker_0"
                segments.append(
                    TranscriptSegment(
                        id=uuid4(),
                        ordinal=start_ordinal + len(segments),
                        speaker_label=label,
                        speaker_display_name=label.replace("_", " ").title(),
                        start_ms=offset_ms + int(start_s * 1000),
                        end_ms=offset_ms + max(int(end_s * 1000), int(start_s * 1000)),
                        text=seg_text,
                        language=str(language_out) if language_out else language,
                        confidence=None,
                    )
                )
        elif text:
            # Fallback when the API returns only plain text.
            duration_hint = max(1_000, len(text.split()) * 400)
            segments.append(
                TranscriptSegment(
                    id=uuid4(),
                    ordinal=start_ordinal,
                    speaker_label="speaker_0",
                    speaker_display_name="Speaker 0",
                    start_ms=offset_ms,
                    end_ms=offset_ms + duration_hint,
                    text=text,
                    language=str(language_out) if language_out else language,
                    confidence=None,
                )
            )

        return NormalizedTranscript(
            segments=segments,
            language=str(language_out) if language_out else language,
            duration_ms=segments[-1].end_ms if segments else offset_ms,
            model_name=model,
            provider="openai",
        )
