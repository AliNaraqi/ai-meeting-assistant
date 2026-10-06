#!/usr/bin/env python3
"""Generate docs/screenshots/demo.gif — storyboard walkthrough under 8 MB.

Requires Pillow (install once): pip install pillow

    python scripts/make_demo_gif.py
"""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install Pillow first: pip install pillow") from exc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots" / "demo.gif"

WIDTH, HEIGHT = 960, 540
BG = (14, 32, 40)
PANEL = (23, 48, 60)
ACCENT = (62, 196, 160)
TEXT = (232, 240, 242)
MUTED = (160, 184, 190)

FRAMES: list[tuple[str, str, list[str]]] = [
    (
        "1 · Upload",
        "Drop a meeting recording",
        ["webm / wav / mp3 / m4a", "Consent confirmed", "Private object storage"],
    ),
    (
        "2 · Processing",
        "Live job progress",
        ["validate → preprocess", "transcribe → extract", "index → ready"],
    ),
    (
        "3 · Transcript",
        "Speaker-aware timeline",
        ["Mina · 00:12", "Ship the Aurora beta Friday", "Noah · 00:28 · I'll own QA"],
    ),
    (
        "4 · Insights",
        "Summary + action items",
        [
            "One-liner: ship Aurora beta Friday",
            "Decision: freeze scope tonight",
            "Action: Noah owns QA checklist",
        ],
    ),
    (
        "5 · Ask + cite",
        "Grounded Q&A with timestamps",
        [
            "Q: Who owns QA?",
            "A: Noah — cites 00:28",
            "Click citation → jump to audio",
        ],
    ),
    (
        "6 · Export",
        "Take it with you",
        ["Markdown · JSON · Slack", "Notion · Actions CSV", "Permanent delete when done"],
    ),
]


def _font(size: int) -> ImageFont.ImageFont:
    for name in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        path = Path(name)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_frame(title: str, subtitle: str, bullets: list[str]) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    margin = 48
    card = [margin, margin, WIDTH - margin, HEIGHT - margin]
    draw.rounded_rectangle(card, radius=18, fill=PANEL, outline=ACCENT, width=2)

    brand = _font(22)
    h1 = _font(36)
    body = _font(24)
    small = _font(18)

    draw.text((margin + 28, margin + 24), "AI Meeting Assistant", fill=ACCENT, font=brand)
    draw.text((margin + 28, margin + 70), title, fill=TEXT, font=h1)
    draw.text((margin + 28, margin + 120), subtitle, fill=MUTED, font=body)

    y = margin + 180
    for bullet in bullets:
        draw.ellipse((margin + 32, y + 8, margin + 44, y + 20), fill=ACCENT)
        draw.text((margin + 58, y), bullet, fill=TEXT, font=small)
        y += 42

    draw.text(
        (margin + 28, HEIGHT - margin - 40),
        "Upload → process → transcript → insights → ask → export",
        fill=MUTED,
        font=small,
    )
    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Solid storyboard only — no product screenshot backdrop (avoids stray UI copy).
    frames = [_draw_frame(title, subtitle, bullets) for title, subtitle, bullets in FRAMES]
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=1200,
        loop=0,
        optimize=True,
    )
    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUT} ({size_mb:.2f} MB)")
    if size_mb > 8:
        raise SystemExit("demo.gif exceeds 8 MB — reduce frames or resolution")


if __name__ == "__main__":
    main()
