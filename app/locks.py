from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator
from uuid import uuid4

from .redis_client import get_redis

logger = logging.getLogger("staycircle.locks")


@contextmanager
def redis_try_lock(key: str, ttl_ms: int = 5000) -> Iterator[bool]:
    """
    Best-effort Redis distributed lock using SET NX PX.
    - Returns True if the lock is acquired (or Redis is unavailable/disabled -> fail-open True).
    - Returns False if another process holds the lock (NX not honored).
    - Ensures safe unlock using a token-matched Lua script.
    - Use small TTLs; this is a coarse per-resource guard (here per-property).
    Usage:
        with redis_try_lock(f"lock:booking:property:{pid}", ttl_ms=5000) as locked:
            if not locked:
                raise HTTPException(429, "please retry")
            # critical section
    """
    r = get_redis()
    if r is None:
        # Fail-open if Redis is disabled/unavailable
        yield True
        return

    token = uuid4().hex
    acquired = False
    try:
        # SET key token NX PX ttl_ms -> True if success, None/False otherwise
        acquired = bool(r.set(key, token, nx=True, px=ttl_ms))
        yield acquired
    except Exception as exc:
        # Fail-open on any unexpected Redis error
        logger.warning("redis_try_lock error (key=%s): %s", key, exc)
        yield True
    finally:
        if acquired:
            # Release only if we still own the lock (token matches)
            try:
                r.eval(
                    """
                    if redis.call('get', KEYS[1]) == ARGV[1] then
                        return redis.call('del', KEYS[1])
                    else
                        return 0
                    end
                    """,
                    1,
                    key,
                    token,
                )
            except Exception as exc:
                # Do not raise; lock will expire by TTL
                logger.debug("redis_try_lock release error (key=%s): %s", key, exc)
