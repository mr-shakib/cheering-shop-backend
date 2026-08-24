"""Idempotent writes — spec §9.

The problem is specific: a customer on cellular data taps Place Order, the
request reaches us and succeeds, and the response is lost on the way back. The
app retries. Without this, they have two orders and two charges.

**The key is claimed before the work runs, not after.** `begin` inserts the row
with `ON CONFLICT DO NOTHING` and inspects what it finds:

* nothing there — this is the first attempt, proceed;
* a row with a stored response — the original succeeded, replay it verbatim;
* a row with no response yet — an identical request is still in flight, so this
  is a genuine double-submit rather than a retry. 409 rather than running the
  work twice and racing.

`request_hash` is compared because a key reused with a *different* body is a
client bug that would otherwise be answered with the first call's response —
which is far more confusing than an error.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.user import IdempotencyKey

# Long enough to cover any plausible retry, short enough that the table stays
# small without a sweeper running often.
_TTL = timedelta(hours=24)


def _hash(body: object) -> str:
    """Stable hash of the request body. `sort_keys` so key order cannot make
    two identical requests look different."""
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode()
    ).hexdigest()


async def begin(
    db: AsyncSession,
    user_id: uuid.UUID,
    key: str | None,
    endpoint: str,
    body: object,
) -> dict | None:
    """Claim the key. Returns the stored response when this is a replay.

    A missing header is allowed through: the endpoint declares the key optional
    and refusing here would break every client that has not adopted it yet.
    The protection is opt-in per request, which is the honest description of
    what an optional header can provide.
    """
    if not key:
        return None

    request_hash = _hash(body)
    now = datetime.now(UTC)
    stmt = (
        insert(IdempotencyKey)
        .values(
            user_id=user_id,
            key=key,
            endpoint=endpoint,
            request_hash=request_hash,
            expires_at=now + _TTL,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "key"])
        .returning(IdempotencyKey.key)
    )
    claimed = await db.scalar(stmt)
    if claimed is not None:
        return None  # First attempt — the caller does the work.

    existing = await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
        )
    )
    if existing is None:  # pragma: no cover - lost a race with expiry cleanup
        return None
    if existing.expires_at < now:
        # Expired: reclaim it rather than replaying a stale response.
        existing.request_hash = request_hash
        existing.endpoint = endpoint
        existing.status_code = None
        existing.response_body = None
        existing.created_at = now
        existing.expires_at = now + _TTL
        await db.flush()
        return None
    if existing.request_hash != request_hash:
        raise ConflictError(
            "That Idempotency-Key was already used with a different request",
            details=["Use a fresh key for a new order."],
        )
    if existing.response_body is None:
        raise ConflictError(
            "An identical request is already being processed",
            details=["Wait for the first one to finish before retrying."],
        )
    return existing.response_body


async def complete(
    db: AsyncSession,
    user_id: uuid.UUID,
    key: str | None,
    status_code: int,
    response_body: dict,
) -> None:
    """Store the response so a retry can replay it."""
    if not key:
        return
    row = await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
        )
    )
    if row is not None:
        row.status_code = status_code
        # Money is Decimal all the way out of the services, and JSONB cannot
        # store it. Encoding here — with the same encoder FastAPI uses on the
        # way to the client — means the replayed body is identical to the one
        # the first attempt actually received, rather than merely equivalent.
        row.response_body = jsonable_encoder(response_body)
        await db.flush()


__all__ = ["begin", "complete"]
