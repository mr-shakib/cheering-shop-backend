"""Delivery offers: every available rider is asked, the first to accept wins.

An *offer* is not a row of its own. It is an order the restaurant has accepted
(PREPARING or READY) that has no rider yet — so there is nothing to create,
expire or clean up, and an order an operator assigns by hand simply stops
being an offer.

* **Who is asked.** Every rider who is on shift, cleared to carry food and not
  blocked. They are told the moment the kitchen accepts, over the rider offers
  WebSocket and by push, and told again when the food is marked ready if
  nobody has taken it yet.
* **Who gets it.** Accepting is one conditional UPDATE —
  `SET rider_id = me WHERE rider_id IS NULL` — so when two riders tap at the
  same moment exactly one row changes and the other rider is told it is
  taken. The rider's own profile row is locked first, so one rider cannot
  race themselves past `MAX_CONCURRENT_JOBS` either.
* **Nobody accepts.** The order waits, visible to operators as awaiting a
  rider; `POST /admin/orders/{id}/assign-rider` still assigns one by hand.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError
from app.core.money import to_major
from app.core.redis import get_rider_location
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order, OrderItem
from app.models.restaurant import Restaurant
from app.models.rider import RiderProfile
from app.models.user import User, UserDevice
from app.schemas.rider import RiderJobDetail, RiderOffer, RiderPosition
from app.services import push_service, realtime
from app.services.pricing import haversine_km
from app.services.rider.dispatch import count_in_flight
from app.services.rider.jobs import job_detail, to_summary
from app.services.rider.tracking import is_fresh

log = structlog.get_logger()

OFFERABLE = (OrderStatus.PREPARING.value, OrderStatus.READY.value)
_MAX_OFFERS = 50


def _open(order_id: uuid.UUID | None = None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        Order.rider_id.is_(None),
        Order.status.in_(OFFERABLE),
    ]
    if order_id is not None:
        conditions.append(Order.id == order_id)
    return conditions


async def _require_available(db: AsyncSession, rider: User, *, lock: bool = False) -> RiderProfile:
    query = select(RiderProfile).where(RiderProfile.user_id == rider.id)
    if lock:
        query = query.with_for_update()
    profile = await db.scalar(query)
    if profile is None:
        raise NotFoundError("That account has no rider profile")
    if not profile.is_verified:
        raise ConflictError("You are not cleared to carry orders yet")
    if not profile.is_online:
        raise ConflictError("Go on shift to see and accept orders")
    return profile


async def list_offers(db: AsyncSession, rider: User) -> list[RiderOffer]:
    """Every open offer. Nearest restaurant first when we know where you are,
    otherwise the ones waiting longest first."""
    await _require_available(db, rider)
    load = await count_in_flight(db, rider.id)

    rows = (
        await db.execute(
            select(Order, Restaurant)
            .join(Restaurant, Restaurant.id == Order.restaurant_id)
            .where(*_open())
            .order_by(Order.accepted_at.asc().nulls_last(), Order.placed_at.asc())
            .limit(_MAX_OFFERS)
        )
    ).all()
    if not rows:
        return []
    quantities = await db.execute(
        select(OrderItem.order_id, func.coalesce(func.sum(OrderItem.quantity), 0))
        .where(OrderItem.order_id.in_([o.id for o, _ in rows]))
        .group_by(OrderItem.order_id)
    )
    counts: dict[uuid.UUID, int] = {oid: int(n) for oid, n in quantities.all()}

    state = await get_rider_location(str(rider.id))
    position = RiderPosition(**state) if state else None
    here = position if is_fresh(position) else None

    offers = []
    for order, restaurant in rows:
        summary = to_summary(order, restaurant, int(counts.get(order.id, 0)))
        offers.append(
            RiderOffer(
                **summary.model_dump(),
                earning=to_major(order.delivery_fee + order.tip),
                distance_to_restaurant_km=round(
                    haversine_km(
                        here.latitude, here.longitude, restaurant.latitude, restaurant.longitude
                    ),
                    2,
                )
                if here
                else None,
                trip_distance_km=round(
                    haversine_km(
                        restaurant.latitude,
                        restaurant.longitude,
                        order.delivery_latitude,
                        order.delivery_longitude,
                    ),
                    2,
                ),
                offered_at=order.accepted_at or order.placed_at,
                can_accept=load < settings.MAX_CONCURRENT_JOBS,
            )
        )
    if here:
        offers.sort(key=lambda o: o.distance_to_restaurant_km or 0.0)
    return offers


async def accept(db: AsyncSession, rider: User, order_id: uuid.UUID) -> RiderJobDetail:
    """First come, first served. `409` if someone else was faster, the order
    was cancelled, or you already carry the maximum."""
    await _require_available(db, rider, lock=True)
    if await count_in_flight(db, rider.id) >= settings.MAX_CONCURRENT_JOBS:
        raise ConflictError(
            f"You already carry {settings.MAX_CONCURRENT_JOBS} orders",
            details=["Deliver one before accepting another"],
        )

    claimed = await db.scalar(
        update(Order)
        .where(*_open(order_id))
        .values(rider_id=rider.id, rider_role=UserRole.RIDER.value, updated_at=datetime.now(UTC))
        .returning(Order.id)
    )
    if claimed is None:
        exists = await db.scalar(
            select(func.count()).select_from(Order).where(Order.id == order_id)
        )
        if not exists:
            raise NotFoundError("Order not found")
        raise ConflictError(
            "This order is no longer available",
            details=["Another rider accepted it first, or it was cancelled"],
        )
    await db.flush()
    log.info("offer_accepted", order_id=str(order_id), rider_id=str(rider.id))
    return await job_detail(db, rider.id, order_id)


async def announce(db: AsyncSession, order_id: uuid.UUID, *, reason: str = "new") -> int:
    """Tell every available rider an order is waiting. Call after the commit.
    Never raises; returns how many devices a push reached."""
    try:
        row = (
            await db.execute(
                select(Order, Restaurant)
                .join(Restaurant, Restaurant.id == Order.restaurant_id)
                .where(*_open(order_id))
            )
        ).first()
        if row is None:
            return 0
        order, restaurant = row
        earning = to_major(order.delivery_fee + order.tip)
        await realtime.publish(
            realtime.rider_offers_channel(),
            {
                "type": "offer.new" if reason == "new" else "offer.ready",
                "order_id": str(order.id),
                "order_number": order.order_number,
                "restaurant_name": restaurant.name,
                "restaurant_latitude": restaurant.latitude,
                "restaurant_longitude": restaurant.longitude,
                "earning": earning,
            },
        )
        tokens = list(
            (
                await db.scalars(
                    select(UserDevice.fcm_token)
                    .join(User, User.id == UserDevice.user_id)
                    .join(RiderProfile, RiderProfile.user_id == User.id)
                    .where(
                        UserDevice.is_active.is_(True),
                        User.is_active.is_(True),
                        RiderProfile.is_online.is_(True),
                        RiderProfile.is_verified.is_(True),
                    )
                )
            ).all()
        )
        title = "New delivery request" if reason == "new" else "Food is ready — still needs a rider"
        pushed = await push_service.send(
            db,
            tokens,
            title,
            f"{restaurant.name} · earn ৳{earning}",
            {"type": "delivery_offer", "order_id": str(order.id)},
        )
        await db.commit()  # persists any tokens push deactivated
        return pushed.sent
    except Exception as exc:  # pragma: no cover - best effort by design
        log.warning("offer_announce_failed", order_id=str(order_id), error=str(exc))
        return 0


async def announce_taken(order_id: uuid.UUID, rider_id: uuid.UUID) -> None:
    """Take the card off every other rider's screen."""
    await realtime.publish(
        realtime.rider_offers_channel(),
        {"type": "offer.taken", "order_id": str(order_id), "rider_id": str(rider_id)},
    )
