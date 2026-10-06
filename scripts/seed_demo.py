#!/usr/bin/env python3
"""Thin wrapper so README can call scripts/seed_demo.py from repo root."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.scripts.seed_demo import main  # noqa: E402

if __name__ == "__main__":
    main()
