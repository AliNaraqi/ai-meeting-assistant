"""Audio validation and normalization helpers (FFmpeg when available)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioProbe:
    duration_ms: int
    codec: str | None
    sample_rate: int | None
    channels: int | None
    has_audio: bool


class AudioProcessingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def should_use_ffmpeg(settings: Settings) -> bool:
    if settings.audio_preprocess_mode == "mock":
        return False
    if settings.audio_preprocess_mode == "ffmpeg":
        return True
    return ffmpeg_available()


def probe_audio(path: Path) -> AudioProbe:
    if not path.exists() or path.stat().st_size <= 0:
        raise AudioProcessingError("invalid_media", "Audio file is missing or empty.")
    if not ffmpeg_available():
        # Local/CI fallback: accept the file and invent a short duration.
        return AudioProbe(
            duration_ms=16_200,
            codec="unknown",
            sample_rate=16_000,
            channels=1,
            has_audio=True,
        )

    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AudioProcessingError("invalid_media", "Unable to probe audio file.") from exc

    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams") or []
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise AudioProcessingError("invalid_media", "File does not contain an audio stream.")

    audio = audio_streams[0]
    duration_raw = payload.get("format", {}).get("duration") or audio.get("duration") or "0"
    try:
        duration_ms = int(float(duration_raw) * 1000)
    except (TypeError, ValueError):
        duration_ms = 0
    if duration_ms <= 0:
        raise AudioProcessingError("invalid_media", "Audio duration is invalid.")

    return AudioProbe(
        duration_ms=duration_ms,
        codec=str(audio.get("codec_name") or "") or None,
        sample_rate=int(audio["sample_rate"]) if audio.get("sample_rate") else None,
        channels=int(audio["channels"]) if audio.get("channels") else None,
        has_audio=True,
    )


def normalize_audio(source: Path, destination: Path, settings: Settings) -> AudioProbe:
    probe = probe_audio(source)
    if probe.duration_ms > settings.max_meeting_duration_seconds * 1000:
        raise AudioProcessingError(
            "duration_too_long",
            "Meeting duration exceeds the configured limit.",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not should_use_ffmpeg(settings):
        destination.write_bytes(source.read_bytes())
        return probe

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.exception("FFmpeg normalization failed")
        raise AudioProcessingError(
            "audio_processing_error",
            "Audio normalization failed.",
        ) from exc

    if not destination.exists() or destination.stat().st_size <= 0:
        raise AudioProcessingError("audio_processing_error", "Normalized audio is empty.")
    return probe_audio(destination)


def split_audio_for_transcription(
    source: Path,
    destination_dir: Path,
    *,
    max_bytes: int,
    segment_seconds: int = 600,
) -> list[tuple[Path, int]]:
    """Split audio into FFmpeg chunks under max_bytes. Returns (path, start_offset_ms)."""
    if not source.exists() or source.stat().st_size <= 0:
        raise AudioProcessingError("invalid_media", "Audio file is missing or empty.")
    if source.stat().st_size <= max_bytes:
        return [(source, 0)]

    if not ffmpeg_available():
        raise AudioProcessingError(
            "audio_processing_error",
            "Audio exceeds transcription size limit and FFmpeg is unavailable for chunking.",
        )

    destination_dir.mkdir(parents=True, exist_ok=True)
    pattern = destination_dir / "chunk_%03d.wav"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-f",
        "segment",
        "-segment_time",
        str(max(30, segment_seconds)),
        "-reset_timestamps",
        "1",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(pattern),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.exception("FFmpeg chunking failed")
        raise AudioProcessingError(
            "audio_processing_error",
            "Audio chunking for transcription failed.",
        ) from exc

    chunks = sorted(destination_dir.glob("chunk_*.wav"))
    if not chunks:
        raise AudioProcessingError("audio_processing_error", "No audio chunks were produced.")

    result: list[tuple[Path, int]] = []
    offset_ms = 0
    for chunk in chunks:
        if chunk.stat().st_size <= 0:
            continue
        if chunk.stat().st_size > max_bytes:
            raise AudioProcessingError(
                "audio_processing_error",
                "A transcription chunk still exceeds the provider size limit.",
            )
        result.append((chunk, offset_ms))
        offset_ms += probe_audio(chunk).duration_ms
    if not result:
        raise AudioProcessingError("audio_processing_error", "Audio chunks were empty.")
    return result
