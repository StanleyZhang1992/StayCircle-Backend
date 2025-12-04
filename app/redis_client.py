import logging
import os
from typing import Optional

_logger = logging.getLogger("staycircle.redis")


def _truthy(val: Optional[str]) -> bool:
    if val is None:
        return False
    return val.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def is_redis_enabled() -> bool:
    return _truthy(os.getenv("REDIS_ENABLED", "false"))


_client = None
_initialized = False


def get_redis():
    """
    Lazy-initialize and return a Redis client if enabled and reachable.
    Fail-open: returns None on any error so callers can gracefully skip Redis usage.
    """
    global _client, _initialized
    if not is_redis_enabled():
        return None
    if _client is not None:
        return _client
    if _initialized and _client is None:
        # Previously attempted and failed; stay fail-open for this process lifetime
        return None

    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    try:
        # Import here to avoid import-time failure before dependencies are installed
        import redis  # type: ignore

        _client = redis.Redis.from_url(
            url,
            socket_timeout=0.25,
            socket_connect_timeout=0.25,
            retry_on_timeout=False,
            health_check_interval=0,
        )
        # Quick health check
        _client.ping()
        _initialized = True
        _logger.info("Connected to Redis at %s", url)
        return _client
    except Exception as exc:
        _logger.warning("Redis unavailable (fail-open): %s", exc)
        _client = None
        _initialized = True
        return None
