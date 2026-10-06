# ADR 0003 — Background job queue

- **Status:** Accepted
- **Date:** 2026-08-05
- **Deciders:** Project owner

## Context

Transcription and LLM extraction can take longer than an HTTP request timeout.
Processing must survive page refresh, report stage progress, and retry safely
without duplicating insights.

## Decision

Use Redis with RQ for the MVP worker queue.

- Web requests enqueue jobs by stable meeting/job IDs
- A dedicated worker process runs validate → preprocess → transcribe → extract →
  index → finalize
- Celery remains an option if scheduling and complex workflows outgrow RQ

Phase 0 ships a stub worker that verifies Redis connectivity until the full
pipeline lands.

## Consequences

- Simple mental model and Docker Compose service layout
- Idempotency keys and job-stage persistence are mandatory
- Horizontal scaling is queue-based rather than request-thread-based
- Migrating to Celery later is possible if the task contract stays ID-centric
