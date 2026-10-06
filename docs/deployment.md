# Deployment

Portfolio deployment targets:

- **Render** for API web service + RQ worker + Redis + nightly retention cron (`render.yaml`)
- **Supabase** for managed Postgres, Auth, and private Storage (production)
- **GitHub Actions** as the quality gate before promoting a release

## Local (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

App: `http://localhost:8000`  
Health: `/health/live`, `/health/ready`  
Ops status: `/status` (JSON: `/api/v1/status`)  
Seed demo:

```bash
cd backend && python -m app.scripts.seed_demo
# or from repo root:
python scripts/seed_demo.py
```

Sign in as `demo@example.com` (dev auth) after seeding, or click **View demo meeting** on the landing page.

## Staging / production (Render + Supabase)

### 1. Supabase project

1. Create a Supabase project.
2. Copy the **Postgres connection string** (URI). Prefer the pooled URI and append `?sslmode=require` if needed. Map it to SQLAlchemy form:

   `postgresql+psycopg://postgres.<ref>:<password>@aws-0-....pooler.supabase.com:6543/postgres?sslmode=require`

3. Enable Auth (email) and create a **private** Storage bucket `meeting-audio`.
4. Copy `SUPABASE_URL`, anon key, JWT secret, and service-role key.

### 2. Render Blueprint

1. Connect the GitHub repo in Render and apply `render.yaml`.
2. Provisioned automatically: `ama-api` (web), `ama-worker` (RQ), `ama-redis`, `ama-retention-purge` (cron `0 3 * * *` UTC).
3. In the dashboard, set shared secrets (leave `OPENAI_API_KEY` **empty** for mock / zero cost):

   | Key | Notes |
   | --- | --- |
   | `DATABASE_URL` | Supabase Postgres URI (`postgresql+psycopg://…`) |
   | `APP_BASE_URL` | `https://<your-render-host>` |
   | `SUPABASE_URL` | Project URL |
   | `SUPABASE_ANON_KEY` | Public anon key |
   | `SUPABASE_JWT_SECRET` | JWT secret from API settings |
   | `SUPABASE_SERVICE_ROLE_KEY` | Service role (storage deletes) |
   | `OPENAI_API_KEY` | Leave blank until you personally demo |

4. `preDeployCommand: alembic upgrade head` runs migrations against Supabase before each web deploy.
5. Confirm `/health/ready` and `/status` after the first deploy.

### 3. Flip OpenAI on for a live demo

Set `OPENAI_API_KEY` on **both** `ama-api` and `ama-worker`, redeploy (or restart). `/status` should show `provider_mode: openai`. Clear the key afterward to return to mocks.

### 4. Nightly retention

Cron service `ama-retention-purge` runs:

```bash
python -m app.scripts.cleanup_expired_audio
```

Manual run:

```bash
python scripts/cleanup_expired_audio.py
```

## Safe operations

- Responses include `X-Request-ID` (echoed from the client when provided).
- Unhandled exceptions return a generic `internal_error` body — no stack traces to clients.
- Docs (`/docs`) are disabled outside development.
- Quotas return `429` with `error.code=quota_exceeded`.
- Upload edge limit: `20` initiates/uploads/completes per IP per UTC day (`MAX_UPLOADS_PER_IP_PER_DAY`), Redis-backed with in-memory fallback (`error.code=rate_limited`).
