# ADR 0002 — Authentication and private audio storage

- **Status:** Accepted
- **Date:** 2026-08-05
- **Deciders:** Project owner

## Context

Meetings contain sensitive audio and transcripts. The API must identify users
server-side, isolate meeting rows by owner, and keep original recordings out of
public object paths. Building a custom auth and object-storage stack would delay
the MVP without improving portfolio signal.

## Decision

Use Supabase for:

- Auth (email/password or passwordless; bearer access tokens validated by FastAPI)
- PostgreSQL as the primary relational store
- Private Storage bucket for meeting audio

The API derives `user_id` from validated JWTs and never trusts a client-supplied
owner ID. Playback uses short-lived signed URLs. Storage object keys are
generated server-side.

## Consequences

- Faster auth/storage bootstrap and a clear privacy story
- Supabase service-role keys remain server/worker-only
- Row-level authorization must still be enforced in FastAPI queries even if
  database RLS is added later
- Local development can mock auth in tests while Compose provides Postgres
