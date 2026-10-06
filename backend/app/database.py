"""SQLAlchemy engine/session helpers and readiness probes."""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _psycopg_conninfo(database_url: str) -> str:
    """Convert SQLAlchemy-style URLs to a psycopg-compatible conninfo string."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine, _SessionLocal
    cfg = settings or get_settings()
    if _engine is None:
        connect_args: dict[str, object] = {}
        engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
        if cfg.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            # In-memory SQLite needs a shared connection pool for tests.
            if ":memory:" in cfg.database_url:
                from sqlalchemy.pool import StaticPool

                engine_kwargs["poolclass"] = StaticPool
                engine_kwargs["pool_pre_ping"] = False
        _engine = create_engine(
            cfg.database_url,
            connect_args=connect_args,
            **engine_kwargs,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    get_engine(settings)
    assert _SessionLocal is not None
    return _SessionLocal


def reset_engine() -> None:
    """Dispose the cached engine (used by tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database(settings: Settings) -> bool:
    """Return True when the configured database accepts a connection."""
    try:
        engine = get_engine(settings)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database readiness check failed")
        return False


def check_redis(settings: Settings) -> bool:
    """Return True when Redis responds to PING.

    Inline job mode does not require Redis, so readiness treats it as optional.
    """
    if settings.job_runner == "inline":
        return True
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        return bool(client.ping())
    except Exception:
        logger.exception("Redis readiness check failed")
        return False
