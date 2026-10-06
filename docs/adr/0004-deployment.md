# ADR 0004 — Portfolio deployment target

- **Status:** Accepted
- **Date:** 2026-08-05
- **Deciders:** Project owner

## Context

The MVP should be reachable from a live HTTPS URL for recruiters, with a worker
process and managed Postgres/auth/storage. The owner should avoid operating
Kubernetes for a single portfolio app.

## Decision

Deploy with:

- Docker images built from this repository
- Render (or equivalent) for the FastAPI web service and background worker
- Supabase for Postgres, Auth, and private Storage
- Redis provided by the hosting platform or a companion service
- GitHub Actions as the quality gate before deploy

Local parity uses Docker Compose (`api`, `worker`, `db`, `redis`).

## Consequences

- Straightforward path from laptop to demo URL
- Cold starts / free-tier sleep may affect demo UX; seed a synthetic meeting
- Secrets stay in the host environment, never in the repository
- `render.yaml` can be added when production services are created
