# Real-provider audio fixture

| File | Notes |
| --- | --- |
| `mtg_001_60s.wav` | ~60s mono 16 kHz tone (stdlib-generated). Upload this for smoke tests. |
| `mtg_001_60s.m4a` | Compressed sibling created with macOS `afconvert`. |
| `mtg_001_60s.mp3` | Created when FFmpeg is available: `python scripts/create_sample_audio.py`. |

## End-to-end check with OpenAI

1. Set `OPENAI_API_KEY` in `.env`.
2. Restart API/worker so logs show `AI provider mode: openai`.
3. Sign in → New meeting → upload `mtg_001_60s.wav` or `.m4a` with consent.
4. Process the meeting.
5. Confirm:
   - transcript is **not** the fixed mock Aurora script (tone fixture will be sparse/empty-ish speech recognition)
   - for a real spoken clip, summary/actions and Ask-this-meeting use model output

Tip: for a meaningful transcript/summary demo, record 30–60s of real speech in the browser instead of the tone fixture.

CI keeps `OPENAI_API_KEY` empty and continues to use mocks.
