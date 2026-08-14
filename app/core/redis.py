"""Redis client and the live-rider geo index.

Decision D2: Redis owns live rider position and nearest-rider dispatch. Postgres
keeps only a decimated audit trail. This is not a cache layer — losing Redis
means live tracking and dispatch stop, so it is a first-class dependency.
"""

from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

# Key namespaces. Kept here so nothing invents key formats inline.
RIDER_GEO_KEY = "riders:geo"  # GEOADD set of online riders
RIDER_STATE_KEY = "rider:{rider_id}:state"  # heading/speed/updated_at hash
ORDER_TRACK_CHANNEL = "order:{order_id}:track"  # pub/sub for the WS fan-out
VENDOR_ALERT_CHANNEL = "vendor:{restaurant_id}:orders"

_pool: aioredis.ConnectionPool | None = None


def get_redis() -> aioredis.Redis:
    """Process-wide client over a shared connection pool."""
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            str(settings.REDIS_URL), decode_responses=True, max_connections=50
        )
    return aioredis.Redis(connection_pool=_pool)


async def check_redis() -> dict[str, Any]:
    """Readiness probe."""
    client = get_redis()
    pong = await client.ping()
    info = await client.info("server")
    return {"status": "ok" if pong else "degraded", "version": info.get("redis_version")}


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.disconnect()
        _pool = None


# ---------------------------------------------------------------------------
# Live rider position — the D2 hot path.
# Implemented in Step 4; signatures fixed here so callers can be written against
# them and so the key layout is decided in exactly one place.
# ---------------------------------------------------------------------------


async def set_rider_location(rider_id: str, lat: float, lng: float, heading: int | None = None):
    """Upsert a rider into the geo index. Called at the full ping rate."""
    raise NotImplementedError("Implemented in Step 4 — Rider module")


async def find_nearby_riders(lat: float, lng: float, radius_m: int, limit: int = 10):
    """GEOSEARCH for dispatch. Replaces the GiST index removed under D2."""
    raise NotImplementedError("Implemented in Step 4 — Dispatch")
