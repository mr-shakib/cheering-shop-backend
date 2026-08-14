"""Background tasks (arq).

Spec §9 makes a task queue a hard requirement: the 60-second vendor auto-decline
cannot be done in-process, because a restart would lose every pending timeout
and orders would hang in PENDING forever.
"""

from datetime import UTC, datetime

import structlog
from arq.connections import RedisSettings

from app.core.config import settings

log = structlog.get_logger()


async def auto_decline_stale_orders(ctx: dict) -> int:
    """Cancel orders a vendor never accepted within the timeout (spec §9).

    Runs on a schedule rather than one deferred job per order: a cron sweep over
    the tiny partial index `ix_orders_auto_decline` is cheaper and self-healing —
    a job lost to a worker crash would strand an order in PENDING, whereas a
    missed sweep simply catches up on the next tick.
    """
    raise NotImplementedError("Implemented in Step 4 — Orders module")


async def flush_rider_trail(ctx: dict) -> int:
    """Decimate live Redis positions into rider_location_pings (decision D2).

    Writes roughly one row per RIDER_TRAIL_DECIMATION_SECONDS instead of one per
    ping — about 1/6th the volume at the default settings.
    """
    raise NotImplementedError("Implemented in Step 4 — Tracking module")


async def recompute_restaurant_rating(ctx: dict, restaurant_id: str) -> None:
    """Refresh the denormalized restaurants.rating_avg after a review lands.

    Done here rather than in a database trigger so a slow aggregate never blocks
    the customer's review write.
    """
    raise NotImplementedError("Implemented in Step 4 — Reviews module")


async def expire_idempotency_keys(ctx: dict) -> int:
    """Garbage-collect idempotency_keys past expires_at."""
    raise NotImplementedError("Implemented in Step 4")


async def startup(ctx: dict) -> None:
    log.info("worker_starting", environment=settings.ENVIRONMENT, at=datetime.now(UTC).isoformat())


async def shutdown(ctx: dict) -> None:
    log.info("worker_stopping")


class WorkerSettings:
    """arq entrypoint: `arq app.workers.tasks.WorkerSettings`."""

    redis_settings = RedisSettings.from_dsn(str(settings.REDIS_URL))
    functions = [
        auto_decline_stale_orders,
        flush_rider_trail,
        recompute_restaurant_rating,
        expire_idempotency_keys,
    ]
    on_startup = startup
    on_shutdown = shutdown
    # cron_jobs are registered in Step 4 alongside the implementations.
