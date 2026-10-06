"""RQ worker process for meeting transcription jobs."""

from __future__ import annotations

import logging
import sys

from redis import Redis
from rq import Worker

from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
)
logger = logging.getLogger("worker.rq")


def main() -> int:
    settings = get_settings()
    redis_conn = Redis.from_url(settings.redis_url)
    logger.info("Starting RQ worker on queue=meeting-processing env=%s", settings.app_env)
    worker = Worker(["meeting-processing"], connection=redis_conn)
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
