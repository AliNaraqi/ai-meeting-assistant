# Architecture

High-level shape of AI Meeting Assistant for Phase 0 and the planned MVP.

## Runtime components

```text
Browser (HTML/CSS/JS)
        │
        ▼
FastAPI app  ──►  PostgreSQL (meetings, transcripts, insights)
        │
        ├──►  Private object storage (audio)
        │
        └──►  Redis queue  ──►  Worker (FFmpeg + AI providers)
```

## Current Phase 0 slice

| Piece | Status |
| --- | --- |
| FastAPI + health probes | Implemented |
| Static landing page | Implemented |
| Docker Compose (api, worker stub, Postgres, Redis) | Implemented |
| CI (Ruff, mypy, pytest, ESLint, Prettier) | Implemented |
| Users/meetings/participants models + Alembic | Implemented |
| Dev auth + authorized meeting CRUD | Implemented |
| Login + dashboard skeleton | Implemented |
| Consent, MediaRecorder, file upload, local private storage | Implemented |
| Jobs + FFmpeg/mock preprocess + mock transcription → segments | Implemented |
| Structured insights/actions with evidence + editable overview | Implemented |
| Meeting workspace (audio/transcript sync, search, rename, export, delete) | Implemented |
| RAG Q&A with chunk index, grounded citations, and chat history | Implemented |
| Quotas, retention cleanup, request IDs, safe errors | Implemented |
| Demo seed script, offline evals, Render blueprint | Implemented |
| Accessibility polish (skip links, labels, focus, live regions) | Implemented |
| Share links, ICS import, Slack/Notion/CSV exports, templates, tab-audio | Implemented |
| Real OpenAI providers when `OPENAI_API_KEY` is set (else mocks) | Implemented |
| Per-user monthly audio/LLM caps + `GET /me/usage` | Implemented |
| PII redaction on stored insights/actions (`REDACT_PII`) | Implemented |
| Delete-forever removes row, audio, embeddings, share links | Implemented |
| Shared “Try me” demo meeting + read-only demo login | Implemented |
| Render web + worker + Redis + retention cron; Supabase Postgres | Implemented |
| Public `/status` ops page (provider, queue, last job) | Implemented |
| IP upload rate limit (20/day) | Implemented |
| Light/dark theme tokens + nav toggle | Implemented |
| Workspace keyboard shortcuts (j/k, space, /, ?) | Implemented |
| Distinct loading / empty / error states | Implemented |

## Deferred from Phase 8

- Full team workspaces / RBAC
- Live OAuth push into Notion/Slack/Linear
- Real-time streaming transcription

## Ops docs

- [Deployment](deployment.md)
- [Evaluation and limitations](evaluation.md)

- Product and roadmap: [PROJECT_PLAN.md](../PROJECT_PLAN.md)
- Data/API/AI contract: [DATA_AND_API_SPEC.md](../DATA_AND_API_SPEC.md)
- Privacy notes: [privacy.md](privacy.md)
- Decision records: [adr/](adr/)

## Principles

1. Long AI work runs in workers, not request threads.
2. Provider APIs stay behind interfaces with CI mocks.
3. Every extracted fact needs transcript evidence or is omitted.
4. Authorization is enforced server-side on every meeting query.
5. Secrets and real recordings never enter the public repository.
