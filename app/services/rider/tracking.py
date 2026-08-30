"""[EXTENDED] Live rider position — decision D2, the half that was missing.

The design was already decided and written down: Redis owns the live position
and nearest-rider matching, Postgres keeps a decimated audit trail, and
`rider_profiles.current_*` holds a last-known value that dispatch must never
read. What did not exist was anything that produced a position, so
`WS /orders/{id}/live-tracking` had nothing to stream and returned 501 rather
than show a courier who was not there.

**Three writes per ping, on three different clocks.** A rider's app reports
every `RIDER_PING_INTERVAL_SECONDS`; at 500 riders that is 100 writes a second,
so what each store costs matters:

* **Redis, every ping.** One pipeline. This is the only copy anything reads
  live.
* **Postgres, every `RIDER_TRAIL_DECIMATION_SECONDS`.** The trail exists to
  settle "where was the rider at 19:40" in a dispute, and 30-second resolution
  answers that. Writing every ping instead would be ~8.6M rows a day for six
  times the fidelity nobody asks for.
* **`rider_profiles`, on the same decimated clock.** An UPDATE per ping would
  generate a dead tuple per ping on a table dispatch reads constantly.

The publish is best-effort like every other one: a rider's position failing to
reach a socket must never fail the ping that carried it, because the next one
is five seconds away.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ForbiddenError, NotFoundError
from app.core.redis import get_redis, get_rider_location, set_rider_location
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order
from app.models.rider import RiderLocationPing, RiderProfile
from app.models.user import User
from app.schemas.rider import LocationAccepted, RiderPosition
from app.services import realtime

log = structlog.get_logger()

# The statuses during which a customer may watch the rider move. Before READY
# there is nothing to follow — the rider is not yet going anywhere on this
# order — and after DELIVERED the journey is over.
TRACKABLE = (OrderStatus.READY, OrderStatus.PICKED_UP)

# Marks when this rider last cost us a Postgres write. A Redis key rather than
# a column precisely because reading it must not touch the table the write is
# trying to spare.
_TRAIL_KEY = "rider:{rider_id}:trail_at"


async def _should_write_trail(rider_id: uuid.UUID) -> bool:
    """True at most once per decimation window, per rider.

    SET NX EX is the whole mechanism: whoever wins the key writes the row, and
    every other ping in the window is refused the key and skips Postgres. It is
    atomic, so two workers handling two pings for the same rider cannot both
    decide they are the one.
    """
    try:
        return bool(
            await get_redis().set(
                _TRAIL_KEY.format(rider_id=rider_id),
                datetime.now(UTC).isoformat(),
                nx=True,
                ex=settings.RIDER_TRAIL_DECIMATION_SECONDS,
            )
        )
    except Exception as exc:  # pragma: no cover - Redis down
        # Fail closed on the expensive side: no Redis means no decimation
        # guard, and writing every ping would be worse than losing the trail.
        log.warning("trail_guard_unavailable", error=str(exc))
        return False


async def _live_orders(db: AsyncSession, rider_id: uuid.UUID) -> list[Order]:
    """The orders whose customers are entitled to see this rider move."""
    rows = await db.execute(
        select(Order).where(
            Order.rider_id == rider_id,
            Order.status.in_([s.value for s in TRACKABLE]),
        )
    )
    return list(rows.scalars().all())


async def record_ping(
    db: AsyncSession,
    rider: User,
    latitude: float,
    longitude: float,
    heading: int | None = None,
    speed_kph: float | None = None,
) -> LocationAccepted:
    """One position report. Cheap on purpose — this is the hottest write here."""
    await set_rider_location(str(rider.id), latitude, longitude, heading, speed_kph)

    now = datetime.now(UTC)
    orders = await _live_orders(db, rider.id)

    trailed = await _should_write_trail(rider.id)
    if trailed:
        # Attached to an order when there is exactly one — a rider carrying two
        # deliveries has one position that belongs to both, and picking either
        # would make the trail lie about which journey it describes.
        db.add(
            RiderLocationPing(
                rider_id=rider.id,
                order_id=orders[0].id if len(orders) == 1 else None,
                latitude=latitude,
                longitude=longitude,
                heading=heading,
                speed_kph=speed_kph,
                recorded_at=now,
            )
        )
        await db.execute(
            update(RiderProfile)
            .where(RiderProfile.user_id == rider.id)
            .values(
                current_latitude=latitude,
                current_longitude=longitude,
                last_location_at=now,
            )
        )
        await db.flush()

    published = 0
    for order in orders:
        if await realtime.publish(
            realtime.order_channel(str(order.id)),
            {
                "type": "rider.location",
                "order_id": str(order.id),
                "status": str(order.status),
                "latitude": latitude,
                "longitude": longitude,
                "heading": heading,
                "speed_kph": speed_kph,
                "recorded_at": now.isoformat(),
            },
        ):
            published += 1

    return LocationAccepted(
        recorded_at=now,
        orders_notified=published,
        trail_written=trailed,
        next_ping_seconds=settings.RIDER_PING_INTERVAL_SECONDS,
    )


async def position_for_order(db: AsyncSession, order: Order) -> RiderPosition | None:
    """The rider's live position, or None — never a stale one.

    Only while the order is in flight. A delivered order's map should show the
    journey that happened, not wherever the courier drove afterwards, which is
    both wrong and none of the customer's business.
    """
    if order.rider_id is None or OrderStatus(str(order.status)) not in TRACKABLE:
        return None
    state = await get_rider_location(str(order.rider_id))
    if state is None:
        return None
    return RiderPosition(**state)


async def authorize_order_channel(
    db: AsyncSession, user_id: uuid.UUID, order_id: uuid.UUID
) -> Order:
    """Who may listen to one order's live channel.

    The customer who placed it and the rider carrying it, and nobody else. The
    vendor is deliberately excluded: they have their own restaurant-scoped
    feed, and a courier's minute-by-minute position after the food has left the
    kitchen is not theirs to watch.

    An order that exists but is not yours is a 404, matching every other
    ownership check in the codebase — a 403 confirms the id is real.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise NotFoundError("No order with that id")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise ForbiddenError("This account cannot open a tracking channel")

    if str(user.role) == UserRole.CUSTOMER and order.customer_id == user_id:
        return order
    if str(user.role) == UserRole.RIDER and order.rider_id == user_id:
        return order
    raise NotFoundError("No order with that id")


async def snapshot(db: AsyncSession, order: Order) -> dict:
    """The first frame a socket receives, so a client that connects mid-journey
    renders immediately instead of waiting up to five seconds for a ping."""
    position = await position_for_order(db, order)
    eta = None
    if order.estimated_delivery_at and OrderStatus(str(order.status)) in TRACKABLE:
        remaining = (order.estimated_delivery_at - datetime.now(UTC)).total_seconds() / 60
        eta = max(0, round(remaining))
    return {
        "type": "tracking.snapshot",
        "order_id": str(order.id),
        "status": str(order.status),
        "eta_minutes": eta,
        "rider_location": position.model_dump(mode="json") if position else None,
        "live_tracking_available": position is not None,
    }


def is_fresh(position: RiderPosition | None) -> bool:
    """Whether a position is recent enough to draw. Redis TTL already evicts
    stale state; this guards the window between a rider going quiet and the key
    expiring."""
    if position is None or position.updated_at is None:
        return False
    age = datetime.now(UTC) - position.updated_at
    return age < timedelta(seconds=settings.RIDER_LOCATION_TTL_SECONDS)
