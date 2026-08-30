"""[EXTENDED] Rider assignment — who carries the order.

Every delivery platform assigns centrally. foodpanda's dispatcher picks from
whoever is on shift and pushes the job to them; the vendor never chooses a
rider and never sees the pool; an operator can override when reality disagrees
with the algorithm. That shape is what this module implements, because it is
the shape the vendor API has to live with permanently —
``POST /vendor/orders/{id}/accept`` must never grow a ``rider_id`` parameter,
and the handoff must never care how the rider got there.

``assign_rider`` is the single entry point. When real dispatch lands — Redis
GEOSEARCH over live positions, batching, shift schedules — ``_pick_rider`` is
the only body that changes and nothing above it moves.

Selection is nearest-first, then load. **Decision D2** is specific about where
"nearest" may come from: Redis GEOSEARCH owns it, and
``rider_profiles.current_latitude/longitude`` are LAST KNOWN, synced
periodically and explicitly not to be read here. A rider who has not pinged
recently has no live position at all and falls back to the load-balanced pool
rather than being placed at a point they may have left ten minutes ago.

So there are two tiers, in this order:

1. **Live and near.** Riders with a fresh Redis position, within
   ``DISPATCH_SEARCH_RADIUS_M`` of the restaurant, nearest first — skipping any
   whose current load would make them a worse choice than the distance
   suggests.
2. **Live but unlocated, or nobody in range.** The idlest rider on shift.

Tier 2 is not a degraded mode. A fleet that has not shipped location reporting
yet, or a rider whose phone lost GPS in a basement, still gets work.
"""

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.redis import find_nearby_riders
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.rider import RiderProfile
from app.models.user import User

log = structlog.get_logger()

# How many geo hits to pull before filtering. Wide enough that a handful of
# fully-loaded riders near the restaurant cannot starve the search, small
# enough that the follow-up query stays a single indexed lookup.
_GEO_CANDIDATES = 20

# Orders that occupy a rider. DELIVERED and CANCELLED have let go of theirs;
# everything else is still in their hands, including PENDING — an order can be
# assigned before the kitchen accepts it.
IN_FLIGHT = (
    OrderStatus.PENDING,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.PICKED_UP,
)

# A rider may still change up to the moment the food does. Once an order is
# PICKED_UP the named rider is holding it, and rewriting the column would
# rewrite history rather than change a plan.
ASSIGNABLE = (OrderStatus.PENDING, OrderStatus.PREPARING, OrderStatus.READY)


def in_flight_counts():
    """Per-rider count of orders currently in hand, as a joinable subquery."""
    return (
        select(Order.rider_id.label("rider_id"), func.count().label("n"))
        .where(
            Order.rider_id.is_not(None),
            Order.status.in_([s.value for s in IN_FLIGHT]),
        )
        .group_by(Order.rider_id)
        .subquery()
    )


async def count_in_flight(db: AsyncSession, rider_id: uuid.UUID) -> int:
    """How many orders this rider is holding right now."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.rider_id == rider_id,
                Order.status.in_([s.value for s in IN_FLIGHT]),
            )
        )
        or 0
    )


def _available_riders_query():
    """On shift, cleared to carry food, account live — with current load.

    Returns the statement and its load expression together. The subquery is
    built once and both are derived from it: constructing a second
    `in_flight_counts()` to order by would reference a table the statement
    never joined, which Postgres rejects outright.
    """
    load = in_flight_counts()
    load_col = func.coalesce(load.c.n, 0)
    stmt = (
        select(User, load_col.label("load"))
        .join(RiderProfile, RiderProfile.user_id == User.id)
        .outerjoin(load, load.c.rider_id == User.id)
        .where(
            User.role == UserRole.RIDER.value,
            User.is_active.is_(True),
            RiderProfile.is_online.is_(True),
            RiderProfile.is_verified.is_(True),
        )
    )
    return stmt, load_col


async def _pick_nearest(db: AsyncSession, latitude: float, longitude: float) -> User | None:
    """Tier 1: the closest rider with a live position, by Redis GEOSEARCH.

    Distance is not the only input. A rider two hundred metres away already
    carrying `MAX_CONCURRENT_JOBS` is a worse choice than one a kilometre out
    with empty hands, because the near one still has to finish what they have
    first — so the loaded ones are skipped and the search falls through to
    whoever is next.

    Geo membership alone proves nothing: a dead app leaves its last point in
    the set forever. Only riders that also survive the availability query —
    online, verified, active — are considered, which is the same filter tier 2
    applies.
    """
    nearby = await find_nearby_riders(
        latitude, longitude, settings.DISPATCH_SEARCH_RADIUS_M, limit=_GEO_CANDIDATES
    )
    if not nearby:
        return None

    order = {rider_id: rank for rank, (rider_id, _) in enumerate(nearby)}
    stmt, _ = _available_riders_query()
    rows = (
        await db.execute(
            stmt.where(User.id.in_([uuid.UUID(rider_id) for rider_id in order]))
        )
    ).all()

    candidates = [
        (order[str(user.id)], user)
        for user, load in rows
        if load < settings.MAX_CONCURRENT_JOBS
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


async def _pick_rider(
    db: AsyncSession, latitude: float | None = None, longitude: float | None = None
) -> User | None:
    """**The seam.** Nearest live rider, else the idlest one on shift.

    Batching, shift schedules and predicted travel time all belong here when
    they land; nothing above this function needs to know they arrived.
    """
    if latitude is not None and longitude is not None:
        nearest = await _pick_nearest(db, latitude, longitude)
        if nearest is not None:
            return nearest

    # Tier 2. The older account breaks a tie, so a quiet shift spreads work in
    # a stable order rather than hammering whichever row Postgres returns first.
    stmt, load_col = _available_riders_query()
    return await db.scalar(stmt.order_by(load_col, User.created_at).limit(1))


async def _resolve_rider(db: AsyncSession, rider_id: uuid.UUID) -> User:
    """The operator override: this rider, named explicitly."""
    rider = await db.get(User, rider_id)
    if rider is None or str(rider.role) != UserRole.RIDER:
        raise NotFoundError("No rider account with that id")
    if not rider.is_active:
        raise ConflictError(
            "That rider account is deactivated",
            details=["Reactivate the account before assigning work to it"],
        )
    profile = await db.get(RiderProfile, rider_id)
    if profile is None or not profile.is_verified:
        raise ConflictError(
            "That rider is not verified",
            details=["Verify the rider before putting them on an order"],
        )
    return rider


async def assign_rider(
    db: AsyncSession, order: Order, rider_id: uuid.UUID | None = None
) -> User:
    """Put a rider on an order. `rider_id` omitted means dispatch chooses.

    Both columns move together or neither does: ``ck_orders_rider_pair``
    requires it, and the composite FK into ``users(id, role)`` is what makes
    "the rider is a RIDER" a property of the data rather than a convention.
    """
    current = OrderStatus(str(order.status))
    if current not in ASSIGNABLE:
        raise ConflictError(
            f"An order that is {current} cannot be assigned a rider",
            details=["A rider can only change up to the moment the food does"],
        )

    if rider_id is None:
        restaurant = await db.get(Restaurant, order.restaurant_id)
        rider = await _pick_rider(
            db,
            latitude=restaurant.latitude if restaurant else None,
            longitude=restaurant.longitude if restaurant else None,
        )
        if rider is None:
            raise ConflictError(
                "No rider is available to take this order",
                details=["Bring a verified rider online, or assign one by id"],
            )
    else:
        rider = await _resolve_rider(db, rider_id)

    previous = order.rider_id
    order.rider_id = rider.id
    order.rider_role = UserRole.RIDER.value
    await db.flush()

    log.info(
        "rider_assigned",
        order_id=str(order.id),
        rider_id=str(rider.id),
        replaced=str(previous) if previous else None,
        chosen_by="operator" if rider_id else "dispatch",
    )
    return rider


async def auto_assign(db: AsyncSession, order: Order) -> User | None:
    """Best effort, called from the order lifecycle. Never raises.

    Dispatch failing is not a reason to refuse a kitchen its order. If nobody
    is on shift the order carries on unassigned and the next lifecycle step
    tries again — a vendor who cannot accept an order because the platform has
    no riders is being punished for someone else's problem. The handoff is
    where the absence finally has to be reported, and it already says so.
    """
    if order.rider_id is not None:
        return None
    try:
        return await assign_rider(db, order)
    except AppError as exc:
        log.info("dispatch_deferred", order_id=str(order.id), reason=exc.message)
        return None


async def assign_to_order(
    db: AsyncSession, order_id: uuid.UUID, rider_id: uuid.UUID | None = None
) -> tuple[Order, User]:
    """The operator entry point: assign by order id, across any restaurant.

    Admins are not scoped to a storefront, so this deliberately does not go
    through the vendor service's restaurant-scoped lookup.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise NotFoundError("No order with that id")
    return order, await assign_rider(db, order, rider_id)
