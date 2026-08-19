"""Redis-backed rate limiting.

Redis rather than in-process counters because the limit must hold across every
worker and every replica. A per-process dict would let an attacker simply spread
attempts over N uvicorn workers and get N times the budget.

Uses a fixed window (INCR + EXPIRE). A sliding window is more precise at the
boundary, but for "stop credential stuffing" the difference is a few extra
attempts once per window — not worth the extra Redis round trips.
"""

from dataclasses import dataclass

import structlog

from app.core.errors import RateLimitedError
from app.core.redis import get_redis

log = structlog.get_logger()


@dataclass(slots=True)
class LimitResult:
    hits: int
    remaining: int
    retry_after: int


async def hit(key: str, *, limit: int, window_seconds: int) -> LimitResult:
    """Count one attempt against `key`. Raises RateLimitedError past `limit`.

    INCR then EXPIRE-on-first-hit is atomic enough for this purpose: the worst
    interleaving loses a single window's TTL, never the counter itself.
    """
    redis = get_redis()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)

    ttl = await redis.ttl(key)
    retry_after = max(ttl, 1)

    if count > limit:
        log.warning("rate_limit_exceeded", key=key, hits=count, limit=limit)
        raise RateLimitedError(
            f"Too many attempts. Try again in {retry_after} seconds",
            headers={"Retry-After": str(retry_after)},
        )

    return LimitResult(hits=count, remaining=max(limit - count, 0), retry_after=retry_after)


async def reset(key: str) -> None:
    """Clear a counter after a legitimate success."""
    await get_redis().delete(key)


def login_identifier_key(identifier: str) -> str:
    return f"rl:login:id:{identifier}"


def login_ip_key(ip: str) -> str:
    return f"rl:login:ip:{ip}"


def otp_verify_key(identifier: str) -> str:
    return f"rl:otpverify:{identifier}"


def application_submit_key(ip: str) -> str:
    return f"rl:vendorapp:submit:{ip}"


def application_upload_key(ip: str) -> str:
    return f"rl:vendorapp:upload:{ip}"
