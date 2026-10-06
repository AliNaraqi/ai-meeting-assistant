"""IP-based upload rate limiting (Redis preferred, in-memory fallback)."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from redis import Redis

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# ip -> (day_key, count)
_memory_counts: dict[str, tuple[str, int]] = defaultdict(lambda: ("", 0))


def _day_key(now: datetime | None = None) -> str:
    stamp = now or datetime.now(UTC)
    return stamp.strftime("%Y-%m-%d")


def _seconds_until_utc_midnight(now: datetime | None = None) -> int:
    stamp = now or datetime.now(UTC)
    tomorrow = stamp.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return max(1, int((tomorrow - stamp).total_seconds()))


def client_ip_from_headers(headers: dict[str, str], fallback: str = "unknown") -> str:
    forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or fallback
    real_ip = headers.get("x-real-ip") or headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return fallback


def _incr_redis(ip: str, settings: Settings) -> int:
    day = _day_key()
    key = f"ama:upload_limit:{ip}:{day}"
    conn = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
    count = int(conn.incr(key))
    if count == 1:
        conn.expire(key, _seconds_until_utc_midnight())
    return count


def _incr_memory(ip: str) -> int:
    day = _day_key()
    with _lock:
        current_day, count = _memory_counts[ip]
        if current_day != day:
            count = 0
            current_day = day
        count += 1
        _memory_counts[ip] = (current_day, count)
        return count


def check_upload_rate_limit(ip: str, settings: Settings | None = None) -> None:
    """Raise 429 when this IP exceeds the daily upload budget."""
    cfg = settings or get_settings()
    limit = int(cfg.max_uploads_per_ip_per_day)
    if limit <= 0:
        return

    try:
        count = _incr_redis(ip, cfg)
    except Exception:
        logger.debug("Redis upload limiter unavailable; using memory", exc_info=True)
        count = _incr_memory(ip)

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": "rate_limited",
                    "message": (
                        f"Upload limit reached ({limit} per day for this network). "
                        "Try again tomorrow."
                    ),
                }
            },
        )


def reset_memory_limits_for_tests() -> None:
    with _lock:
        _memory_counts.clear()
