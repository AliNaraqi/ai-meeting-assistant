"""Purge expired audio recordings past retention_until.

Usage:

    python -m app.scripts.cleanup_expired_audio
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.database import get_session_factory, reset_engine
from app.services.retention import purge_expired_audio


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    reset_engine()
    db = get_session_factory(settings)()
    try:
        result = purge_expired_audio(db, settings)
        db.commit()
        print(result)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
