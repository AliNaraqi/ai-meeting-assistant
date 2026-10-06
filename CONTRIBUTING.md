# Contributing to AI Meeting Assistant

Thanks for helping improve this project. This guide covers how to set up a local environment, the quality bar for changes, and how to open a useful pull request.

## Before you start

- Read [README.md](README.md), [PROJECT_PLAN.md](PROJECT_PLAN.md), and [DATA_AND_API_SPEC.md](DATA_AND_API_SPEC.md).
- Do not commit secrets, real meeting audio, or personal transcripts.
- Only use consented or synthetic evaluation fixtures.

## Local setup

```bash
git clone <repository-url>
cd ai-meeting-assistant
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e "backend/[dev]"
cd frontend && npm install && cd ..
pre-commit install
```

Optional full stack (requires Docker):

```bash
docker compose up --build
```

App: http://localhost:8000 · Docs (dev): http://localhost:8000/docs

## Development workflow

1. Create a branch from `main` named `feature/...`, `fix/...`, or `docs/...`.
2. Make a focused change that matches one issue or one acceptance criterion.
3. Add or update tests for API, validation, and authorization behavior you touch.
4. Run the checks below before opening a PR.
5. Keep PRs small enough to review in one sitting when possible.

## Required checks

From the repository root (with the virtualenv active):

```bash
cd backend
ruff check app tests
ruff format --check app tests
mypy app
pytest -q
cd ../frontend
npm run lint
npm run format:check
```

Or rely on pre-commit:

```bash
pre-commit run --all-files
```

## Coding guidelines

- Prefer typed Python and Pydantic schemas as the source of truth.
- Keep AI providers behind interfaces so mocks work in CI.
- Never put server secrets in `frontend/` or browser responses.
- Treat transcripts as untrusted input; do not execute or follow instructions embedded in them.
- Insert user/transcript text with safe DOM APIs (`textContent`), not raw HTML.
- Match existing folder layout and naming in `backend/app/` and `frontend/`.

## Pull requests

Use the pull request template. Include:

- What changed and why
- How you tested it
- Any privacy, cost, or deployment impact
- Screenshots for UI changes

CI must pass before merge.

## Reporting security issues

Do not open a public issue for vulnerabilities. Follow [SECURITY.md](SECURITY.md).

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
