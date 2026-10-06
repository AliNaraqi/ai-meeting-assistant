"""Worker stub for Phase 0.

Verifies Redis connectivity and idles until the real RQ/Celery pipeline is added.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
)
logger = logging.getLogger("worker.stub")

_running = True


def _handle_stop(signum: int, _frame: object) -> None:
    global _running
    logger.info("Received signal %s; shutting down stub worker.", signum)
    _running = False


def _ping_redis(redis_url: str) -> None:
    import redis

    client = redis.Redis.from_url(redis_url, socket_connect_timeout=5)
    client.ping()


def main() -> int:
    settings = get_settings()
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    logger.info(
        "Starting stub worker (env=%s). Queue consumer arrives in a later phase.",
        settings.app_env,
    )

    if not settings.redis_url:
        logger.error("REDIS_URL is not configured.")
        return 1

    while _running:
        try:
            _ping_redis(settings.redis_url)
            logger.info("Redis reachable. Stub worker idle.")
        except Exception:
            logger.exception("Redis ping failed; will retry.")
        for _ in range(30):
            if not _running:
                break
            time.sleep(1)

    logger.info("Stub worker stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
