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

What this deliberately does NOT do is geography. **Decision D2** states that
``rider_profiles.current_latitude/longitude`` are LAST KNOWN, synced
periodically from Redis, not authoritative, and must not be read by dispatch.
Choosing "the nearest rider" from a column that may be minutes stale is worse
than not choosing on distance at all — it looks correct and is wrong. So
selection balances load instead: of the riders on shift, the one holding the
fewest orders.
"""

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order
from app.models.rider import RiderProfile
from app.models.user import User

log = structlog.get_logger()

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


async def _pick_rider(db: AsyncSession) -> User | None:
    """**The seam.** Replace this body, not its callers, when dispatch is real.

    On shift, cleared to carry food, account live. Fewest orders in hand wins;
    the older account breaks a tie, so a quiet shift spreads work in a stable
    order rather than hammering whichever row Postgres returns first.
    """
    load = in_flight_counts()
    return await db.scalar(
        select(User)
        .join(RiderProfile, RiderProfile.user_id == User.id)
        .outerjoin(load, load.c.rider_id == User.id)
        .where(
            User.role == UserRole.RIDER.value,
            User.is_active.is_(True),
            RiderProfile.is_online.is_(True),
            RiderProfile.is_verified.is_(True),
        )
        .order_by(func.coalesce(load.c.n, 0), User.created_at)
        .limit(1)
    )


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
        rider = await _pick_rider(db)
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
