"""Redis pub/sub fan-out for WebSocket channels — decision D2.

**Why Redis rather than a process-local queue.** Uvicorn runs several workers
and Dokploy can run several containers. A customer's socket may be held by one
worker while the order that concerns them is placed on another. An in-process
list would deliver to whoever happened to accept the socket and silently drop
everything else — a vendor tablet that misses an order is a cold meal.

Publishing is deliberately best-effort: an order must still be placed when
Redis is unreachable. The vendor falls back to polling, which is what they do
today anyway. A failed publish is logged, never raised.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog

from app.core.redis import get_redis

log = structlog.get_logger()


def vendor_channel(restaurant_id: str) -> str:
    return f"vendor:{restaurant_id}:orders"


def order_channel(order_id: str) -> str:
    return f"order:{order_id}:track"


async def publish(channel: str, payload: dict[str, Any]) -> bool:
    """Fire a message at a channel. Never raises.

    Returns whether it went out, so a caller that wants to tell the client
    "delivered live" can say so honestly rather than assuming.
    """
    try:
        client = get_redis()
        await client.publish(channel, json.dumps(payload, default=str))
        return True
    except Exception as exc:  # pragma: no cover - depends on Redis being down
        log.warning("realtime_publish_failed", channel=channel, error=str(exc))
        return False


@asynccontextmanager
async def subscribe(channel: str) -> AsyncIterator[AsyncIterator[dict]]:
    """Subscribe for the life of a `with` block, unsubscribing on exit.

    The context manager exists so a dropped WebSocket cannot leak a Redis
    subscription — without it, every disconnect would leave a subscriber
    holding a connection until the pool was exhausted.
    """
    client = get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)

    async def _messages() -> AsyncIterator[dict]:
        async for raw in pubsub.listen():
            if raw.get("type") != "message":
                continue
            try:
                yield json.loads(raw["data"])
            except (ValueError, TypeError):  # pragma: no cover - malformed publisher
                log.warning("realtime_bad_payload", channel=channel)

    try:
        yield _messages()
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


__all__ = ["order_channel", "publish", "subscribe", "vendor_channel"]
