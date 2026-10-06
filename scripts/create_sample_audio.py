#!/usr/bin/env python3
"""Create a ~60s sample audio fixture for real OpenAI end-to-end checks.

Produces:
  evals/fixtures/mtg_001_60s.wav
and, when FFmpeg is installed:
  evals/fixtures/mtg_001_60s.mp3
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evals" / "fixtures"
WAV_PATH = FIXTURES / "mtg_001_60s.wav"
MP3_PATH = FIXTURES / "mtg_001_60s.mp3"


def write_wav(path: Path, *, duration_s: int = 60, rate: int = 16_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    amp = 0.15
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = bytearray()
        for i in range(rate * duration_s):
            t = i / rate
            if int(t) % 5 in {0, 1, 2}:
                sample = int(amp * 32767 * math.sin(2 * math.pi * 220 * t))
            else:
                sample = 0
            frames += struct.pack("<h", sample)
        wf.writeframes(frames)


def maybe_write_mp3(wav_path: Path, mp3_path: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    subprocess.run(
        [ffmpeg, "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-qscale:a", "4", str(mp3_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return True


def main() -> None:
    write_wav(WAV_PATH)
    print(f"wrote {WAV_PATH}")
    if maybe_write_mp3(WAV_PATH, MP3_PATH):
        print(f"wrote {MP3_PATH}")
    else:
        print("ffmpeg not found; skipped mp3 (upload the .wav instead)")


if __name__ == "__main__":
    main()
