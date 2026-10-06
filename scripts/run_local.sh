#!/usr/bin/env bash
# Free local run — no Docker / Redis / Postgres / OpenAI required.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install -q -U pip
python -m pip install -q -e "./backend[dev]"

mkdir -p data/audio backend/data
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit if needed."
fi

cd backend
export PYTHONPATH=.
echo "Starting AI Meeting Assistant at http://localhost:8000"
echo "  Landing:  http://localhost:8000/"
echo "  Demo:     click View demo meeting"
echo "  Status:   http://localhost:8000/status"
exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
