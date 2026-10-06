# Evaluation and limitations

Offline evaluation lives under `evals/` and uses **mock providers** so CI never spends API credits.

## Run

```bash
python evals/run_evals.py --fixture mtg_001
```

Results are written to `evals/results/`. Exit code `0` means all cases passed.

## What is measured (v1)

| Area | Check |
| --- | --- |
| Insights | Evidence IDs exist; summary/decision/action keyword presence |
| Q&A | `answer_status` matches gold; citations land on expected ordinals; abstain when unsupported |
| Safety | Prompt-injection text in transcripts is ignored by the mock QA provider |

Rubrics: `evals/rubrics/`.

## Current limitations (publish with demos)

1. Transcription, extraction, embeddings, and Q&A default to deterministic mocks unless real provider keys and adapters are configured.
2. Semantic retrieval stores embeddings as JSON and ranks with cosine similarity in-process; pgvector can replace this later.
3. Browser recording captures the local microphone, not all remote meeting-platform audio.
4. Quotas and retention are application-enforced; production still needs scheduled cleanup and monitoring.
5. Screenshots / demo GIF should be refreshed whenever the UI changes materially.
6. Evaluation coverage is synthetic (`mtg_001`); expand fixtures before claiming production quality.

## Screenshots

Place recruiter-facing captures in `docs/screenshots/`:

- Landing
- Dashboard with demo meeting
- Workspace (transcript + ask)
