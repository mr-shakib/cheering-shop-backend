"""Redis client and the live-rider geo index.

Decision D2: Redis owns live rider position and nearest-rider dispatch. Postgres
keeps only a decimated audit trail. This is not a cache layer — losing Redis
means live tracking and dispatch stop, so it is a first-class dependency.
"""

from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.core.config import settings

log = structlog.get_logger()

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
#
# Two structures, because they answer two different questions:
#
#   riders:geo         a GEO set — "who is near this restaurant?" (dispatch)
#   rider:{id}:state   a hash    — "where exactly is this rider, and how fresh
#                                  is that?" (the customer's map)
#
# The hash carries the TTL and the geo set does not, because GEO members cannot
# expire individually. That asymmetry is deliberate and load-bearing: a rider
# whose app died leaves a stale point in the geo set, and the missing hash is
# how everything downstream knows to ignore it. Freshness is a property of the
# hash, never of the geo membership.
# ---------------------------------------------------------------------------


def _state_key(rider_id: str) -> str:
    return RIDER_STATE_KEY.format(rider_id=rider_id)


async def set_rider_location(
    rider_id: str,
    lat: float,
    lng: float,
    heading: int | None = None,
    speed_kph: float | None = None,
) -> None:
    """Upsert a rider into the geo index. Called at the full ping rate.

    One pipeline per ping: at five seconds per rider this runs thousands of
    times a minute, and three round trips where one will do is the difference
    between Redis idling and Redis being the bottleneck.
    """
    client = get_redis()
    now = datetime.now(UTC).isoformat()
    pipe = client.pipeline(transaction=False)
    pipe.geoadd(RIDER_GEO_KEY, (lng, lat, rider_id))
    pipe.hset(
        _state_key(rider_id),
        mapping={
            "lat": lat,
            "lng": lng,
            "heading": "" if heading is None else heading,
            "speed_kph": "" if speed_kph is None else speed_kph,
            "updated_at": now,
        },
    )
    pipe.expire(_state_key(rider_id), settings.RIDER_LOCATION_TTL_SECONDS)
    await pipe.execute()


async def get_rider_location(rider_id: str) -> dict[str, Any] | None:
    """Where a rider is, or None if nobody has heard from them recently.

    None is the honest answer to a stale rider and callers must render it as
    "no live position" rather than falling back to the last point they saw —
    a dot frozen on a map for ten minutes reads as a courier who has stopped,
    not as an app that has gone quiet.
    """
    # redis-py types hgetall as sync-or-async for the shared client class;
    # this pool is always async, so the await is correct and the union is not.
    state: dict[str, str] = await get_redis().hgetall(_state_key(rider_id))  # type: ignore[misc]
    if not state:
        return None
    return {
        "latitude": float(state["lat"]),
        "longitude": float(state["lng"]),
        "heading": int(state["heading"]) if state.get("heading") else None,
        "speed_kph": float(state["speed_kph"]) if state.get("speed_kph") else None,
        "updated_at": state.get("updated_at"),
    }


async def find_nearby_riders(
    lat: float, lng: float, radius_m: int, limit: int = 10
) -> list[tuple[str, float]]:
    """GEOSEARCH for dispatch. Replaces the GiST index removed under D2.

    Returns `(rider_id, metres)` nearest first. Membership alone does not mean
    a rider is live — the caller must still check that each one has a state
    hash, since a dead app leaves its last point behind in the set.
    """
    try:
        rows = await get_redis().geosearch(
            RIDER_GEO_KEY,
            longitude=lng,
            latitude=lat,
            radius=radius_m,
            unit="m",
            withdist=True,
            sort="ASC",
            count=limit,
        )
    except Exception as exc:  # pragma: no cover - Redis down or key absent
        log.warning("geosearch_failed", error=str(exc))
        return []
    return [(str(member), float(distance)) for member, distance in rows]


async def drop_rider_location(rider_id: str) -> None:
    """Forget a rider entirely — clocking off, or going inactive.

    Removes the geo member as well as the hash. Letting a point linger for an
    off-shift rider would put them back in dispatch range the moment somebody
    searched a radius wide enough to reach it.
    """
    client = get_redis()
    pipe = client.pipeline(transaction=False)
    pipe.zrem(RIDER_GEO_KEY, rider_id)
    pipe.delete(_state_key(rider_id))
    await pipe.execute()
