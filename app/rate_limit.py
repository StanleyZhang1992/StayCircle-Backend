import os
import logging
from typing import Callable, Literal, Optional

from fastapi import Request, HTTPException, status

from .redis_client import get_redis, is_redis_enabled

logger = logging.getLogger("staycircle.rate_limit")

Scope = Literal["login", "signup", "write"]


def _to_int(val: Optional[str], default: int) -> int:
    try:
        return int(val) if val is not None else default
    except Exception:
        return default


def _window_seconds() -> int:
    return _to_int(os.getenv("RATE_LIMIT_WINDOW_SECONDS"), 60)


def _limit_for_scope(scope: Scope) -> int:
    if scope == "login":
        return _to_int(os.getenv("RATE_LIMIT_LOGIN_PER_WINDOW"), 10)
    if scope == "signup":
        return _to_int(os.getenv("RATE_LIMIT_SIGNUP_PER_WINDOW"), 5)
    # default for writes
    return _to_int(os.getenv("RATE_LIMIT_WRITE_PER_WINDOW"), 30)


def _client_ip(request: Request) -> str:
    # Minimal implementation: rely on server connection IP; XFF support can be added later.
    try:
        if request.client and request.client.host:
            return request.client.host
    except Exception:
        pass
    return "unknown"


def rate_limit(scope: Scope) -> Callable[[Request], None]:
    """
    Fixed-window Redis-backed rate limit dependency.
    Minimal scope: per-IP counters only (no user coupling to avoid circular deps).
    - Keys: rl:v1:ip:{ip}:{scope}
    - Window: RATE_LIMIT_WINDOW_SECONDS (default 60s)
    - Limits per window:
        * login:  RATE_LIMIT_LOGIN_PER_WINDOW (default 10)
        * signup: RATE_LIMIT_SIGNUP_PER_WINDOW (default 5)
        * write:  RATE_LIMIT_WRITE_PER_WINDOW  (default 30)
    Fail-open behavior if Redis disabled/unavailable.
    """
    window = _window_seconds()
    limit = _limit_for_scope(scope)

    def _dependency(request: Request) -> None:
        if not is_redis_enabled():
            return

        r = get_redis()
        if r is None:
            # Fail-open: Redis disabled or unreachable
            return

        ip = _client_ip(request)
        key = f"rl:v1:ip:{ip}:{scope}"
        try:
            current = r.incr(key, amount=1)
            if current == 1:
                # First hit in window: set TTL
                r.expire(key, window)
            if current > limit:
                ttl = r.ttl(key)
                retry_after = ttl if isinstance(ttl, int) and ttl > 0 else window
                detail = {
                    "error": "rate_limited",
                    "scope": scope,
                    "ip": ip,
                    "limit": limit,
                    "window_seconds": window,
                    "retry_after": retry_after,
                }
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)
        except HTTPException:
            raise
        except Exception as exc:
            # Fail-open on any Redis error
            logger.warning("Rate limit fail-open (scope=%s, ip=%s): %s", scope, ip, exc)
            return

    return _dependency
