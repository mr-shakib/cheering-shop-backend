"""Background tasks (arq).

Spec §9 makes a task queue a hard requirement: the 60-second vendor auto-decline
cannot be done in-process, because a restart would lose every pending timeout
and orders would hang in PENDING forever.

**Registering a function is not enough — it must appear in `cron_jobs` below or
nothing ever calls it.** The retention jobs are the whole reason this worker
exists today; without the schedule, `otp_codes`, `refresh_tokens` and
`idempotency_keys` grow without bound until the disk fills.
"""

from datetime import UTC, datetime, timedelta

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import delete, or_

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.user import IdempotencyKey, OtpCode, RefreshToken

log = structlog.get_logger()

# How long spent credentials are kept after they stop being useful. Not zero:
# a short tail is invaluable when investigating "I never got my code" or a
# suspected token-theft incident.
OTP_RETENTION = timedelta(days=2)
REFRESH_TOKEN_RETENTION = timedelta(days=30)


async def prune_expired_otps(ctx: dict) -> int:
    """Delete OTPs that are consumed or long expired.

    One row per signup attempt, per resend, per password reset. At any real
    volume this is the fastest-growing table in the schema and none of it has
    value after a couple of days.
    """
    cutoff = datetime.now(UTC) - OTP_RETENTION
    async with SessionLocal() as db:
        result = await db.execute(
            delete(OtpCode).where(
                or_(OtpCode.consumed_at.is_not(None), OtpCode.expires_at < cutoff),
                OtpCode.created_at < cutoff,
            )
        )
        await db.commit()
    deleted = result.rowcount or 0
    if deleted:
        log.info("pruned_otp_codes", deleted=deleted)
    return deleted


async def prune_expired_refresh_tokens(ctx: dict) -> int:
    """Delete refresh tokens that are long expired or long revoked.

    Kept for 30 days past expiry on purpose: `replaced_by_id` forms the rotation
    chain used to detect token reuse, and pruning too eagerly would erase the
    evidence that a stolen token was replayed.
    """
    cutoff = datetime.now(UTC) - REFRESH_TOKEN_RETENTION
    async with SessionLocal() as db:
        result = await db.execute(
            delete(RefreshToken).where(
                RefreshToken.expires_at < cutoff,
                or_(RefreshToken.revoked_at.is_(None), RefreshToken.revoked_at < cutoff),
            )
        )
        await db.commit()
    deleted = result.rowcount or 0
    if deleted:
        log.info("pruned_refresh_tokens", deleted=deleted)
    return deleted


async def expire_idempotency_keys(ctx: dict) -> int:
    """Garbage-collect idempotency_keys past expires_at (spec §9)."""
    async with SessionLocal() as db:
        result = await db.execute(
            delete(IdempotencyKey).where(IdempotencyKey.expires_at < datetime.now(UTC))
        )
        await db.commit()
    deleted = result.rowcount or 0
    if deleted:
        log.info("pruned_idempotency_keys", deleted=deleted)
    return deleted


# ---------------------------------------------------------------------------
# Order lifecycle — implemented with their modules in Step 4
# ---------------------------------------------------------------------------
async def auto_decline_stale_orders(ctx: dict) -> int:
    """Cancel orders a vendor never accepted within the timeout (spec §9).

    A cron sweep over the tiny partial index `ix_orders_auto_decline` rather
    than one deferred job per order: the sweep is cheaper and self-healing — a
    job lost to a worker crash would strand an order in PENDING forever, whereas
    a missed sweep simply catches up on the next tick.
    """
    raise NotImplementedError("Implemented with the Orders module")


async def flush_rider_trail(ctx: dict) -> int:
    """Decimate live Redis positions into rider_location_pings (decision D2)."""
    raise NotImplementedError("Implemented with the Tracking module")


async def recompute_restaurant_rating(ctx: dict, restaurant_id: str) -> None:
    """Refresh the denormalized restaurants.rating_avg after a review lands.

    Done here rather than in a database trigger so a slow aggregate never blocks
    the customer's review write.
    """
    raise NotImplementedError("Implemented with the Reviews module")


async def startup(ctx: dict) -> None:
    log.info("worker_starting", environment=settings.ENVIRONMENT, at=datetime.now(UTC).isoformat())


async def shutdown(ctx: dict) -> None:
    log.info("worker_stopping")


class WorkerSettings:
    """arq entrypoint: `arq app.workers.tasks.WorkerSettings`."""

    redis_settings = RedisSettings.from_dsn(str(settings.REDIS_URL))
    functions = [
        prune_expired_otps,
        prune_expired_refresh_tokens,
        expire_idempotency_keys,
        auto_decline_stale_orders,
        flush_rider_trail,
        recompute_restaurant_rating,
    ]
    # Staggered minutes so three DELETEs never land on the database at once.
    cron_jobs = [
        cron(prune_expired_otps, hour=3, minute=10),
        cron(prune_expired_refresh_tokens, hour=3, minute=20),
        cron(expire_idempotency_keys, hour=3, minute=30),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    job_timeout = 300
