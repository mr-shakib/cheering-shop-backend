"""The admin rider screens: Active Rider, Rider Details and its tabs, Rider
Withdrawal, and Live Tracking.

Shift, clearance and passwords still go through the roster module, the one
place dispatch's two flags are written; this module adds the profile fields,
the money views and the live map.
"""

import uuid

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ValidationError
from app.core.money import to_major
from app.core.redis import get_rider_location
from app.models.enums import OrderStatus, PayoutStatus, UserRole
from app.models.order import Order
from app.models.payout import RiderPayout
from app.models.restaurant import Restaurant
from app.models.rider import RiderIncentive, RiderProfile
from app.models.user import User
from app.schemas.admin import (
    AdminRiderDetail,
    AdminRiderEarnings,
    AdminRiderPayoutRow,
    AdminRiderRow,
    LiveOrderBrief,
    LiveRider,
    RiderIncentiveOut,
)
from app.schemas.requests import RiderUpdateRequest
from app.schemas.rider import RiderPosition
from app.services.admin.common import day_window, like_pattern, parse_uuid
from app.services.pricing import haversine_km
from app.services.rider import earnings, roster
from app.services.rider.dispatch import IN_FLIGHT, in_flight_counts
from app.services.rider.tracking import is_fresh

log = structlog.get_logger()

_PROFILE_FIELDS = (
    "vehicle_type",
    "license_number",
    "date_of_birth",
    "national_id",
    "documents",
)


def _to_row(user: User, profile: RiderProfile, in_flight: int) -> AdminRiderRow:
    return AdminRiderRow(
        **roster.to_out(user, profile, in_flight).model_dump(),
        avatar_url=user.avatar_url,
        rating_avg=float(profile.rating_avg),
        rating_count=profile.rating_count,
        live_status="ONLINE" if profile.is_online else "OFFLINE",
    )


async def list_riders(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    online_only: bool = False,
    q: str | None = None,
    vehicle_type: str | None = None,
    min_rating: float | None = None,
    status: str | None = None,
) -> tuple[list[AdminRiderRow], int]:
    """Online first, then the least loaded — the order dispatch picks in, so
    an operator overriding a choice sees the list it was choosing from.

    `status`: ACTIVE (not blocked, cleared to ride), SUSPENDED (not cleared) or
    BLOCKED (account blocked). Omitted means everyone."""
    load = in_flight_counts()
    n = func.coalesce(load.c.n, 0)
    conditions: list[ColumnElement[bool]] = [User.role == UserRole.RIDER.value]
    if online_only:
        conditions.append(RiderProfile.is_online.is_(True))
    if q and q.strip():
        pattern = like_pattern(q.strip())
        conditions.append(
            or_(User.full_name.ilike(pattern), User.phone.ilike(pattern), User.email.ilike(pattern))
        )
    if vehicle_type:
        conditions.append(func.upper(RiderProfile.vehicle_type) == vehicle_type.strip().upper())
    if min_rating is not None:
        conditions.append(RiderProfile.rating_avg >= min_rating)
    if status:
        wanted = status.strip().upper()
        if wanted == "ACTIVE":
            conditions += [User.is_active.is_(True), RiderProfile.is_verified.is_(True)]
        elif wanted == "SUSPENDED":
            conditions.append(RiderProfile.is_verified.is_(False))
        elif wanted == "BLOCKED":
            conditions.append(User.is_active.is_(False))
        else:
            raise ValidationError("status must be ACTIVE, SUSPENDED or BLOCKED")

    base = (
        select(User, RiderProfile, n)
        .join(RiderProfile, RiderProfile.user_id == User.id)
        .outerjoin(load, load.c.rider_id == User.id)
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = await db.execute(
        base.order_by(RiderProfile.is_online.desc(), n, User.full_name).limit(limit).offset(offset)
    )
    return [_to_row(u, p, int(k)) for u, p, k in rows.all()], total


async def get_rider(db: AsyncSession, rider_id: uuid.UUID) -> AdminRiderDetail:
    user, profile = await roster.get_rider(db, rider_id)
    in_flight = await db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.rider_id == rider_id, Order.status.in_([s.value for s in IN_FLIGHT]))
    )
    rows = await db.execute(
        select(Order.status, func.count())
        .where(
            Order.rider_id == rider_id,
            Order.status.in_([OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value]),
        )
        .group_by(Order.status)
    )
    counts: dict[str, int] = {str(status): int(n) for status, n in rows.all()}
    return AdminRiderDetail(
        **_to_row(user, profile, int(in_flight or 0)).model_dump(),
        date_of_birth=profile.date_of_birth,
        national_id=profile.national_id,
        documents={k: str(v) for k, v in (profile.documents or {}).items() if v},
        payout=profile.payout or {},
        delivered_orders=int(counts.get(OrderStatus.DELIVERED.value, 0)),
        cancelled_orders=int(counts.get(OrderStatus.CANCELLED.value, 0)),
        earnings=await earnings.summary(db, rider_id),
    )


async def update_rider(
    db: AsyncSession, rider_id: uuid.UUID, body: RiderUpdateRequest
) -> AdminRiderDetail:
    fields = body.model_dump(exclude_unset=True)
    if {"is_online", "is_verified", "password"} & fields.keys():
        await roster.set_flags(
            db,
            rider_id,
            is_online=body.is_online,
            is_verified=body.is_verified,
            password=body.password,
        )
    user, profile = await roster.get_rider(db, rider_id)
    if fields.get("full_name") is not None:
        user.full_name = fields["full_name"].strip()
    for field in _PROFILE_FIELDS:
        if field in fields:
            setattr(profile, field, fields[field] if field != "documents" else fields[field] or {})
    await db.flush()
    return await get_rider(db, rider_id)


async def rider_earnings(
    db: AsyncSession, rider_id: uuid.UUID, limit: int, offset: int
) -> tuple[AdminRiderEarnings, int]:
    await roster.get_rider(db, rider_id)
    days, total = await earnings.daily(db, rider_id, limit, offset)
    return AdminRiderEarnings(summary=await earnings.summary(db, rider_id), days=days), total


async def grant_incentive(
    db: AsyncSession, admin: User, rider_id: uuid.UUID, amount, reason: str
) -> RiderIncentiveOut:
    incentive = await earnings.grant_incentive(db, admin, rider_id, amount, reason)
    return _incentive_out(incentive)


def _incentive_out(incentive: RiderIncentive) -> RiderIncentiveOut:
    return RiderIncentiveOut(
        id=str(incentive.id),
        rider_id=str(incentive.rider_id),
        amount=to_major(incentive.amount),
        reason=incentive.reason,
        created_by=str(incentive.created_by) if incentive.created_by else None,
        created_at=incentive.created_at,
    )


# ---------------------------------------------------------------------------
# Withdrawals
# ---------------------------------------------------------------------------


def payout_row(payout: RiderPayout, rider: User | None) -> AdminRiderPayoutRow:
    return AdminRiderPayoutRow(
        **earnings.to_out(payout).model_dump(),
        rider_name=rider.full_name if rider else None,
        rider_avatar_url=rider.avatar_url if rider else None,
        reopened_at=payout.reopened_at,
        reopen_reason=payout.reopen_reason,
    )


async def payout_row_by_id(db: AsyncSession, payout: RiderPayout) -> AdminRiderPayoutRow:
    return payout_row(payout, await db.get(User, payout.rider_id))


async def list_payouts(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = PayoutStatus.PROCESSING.value,
    rider_id: str | None = None,
    q: str | None = None,
    date_from=None,
    date_to=None,
) -> tuple[list[AdminRiderPayoutRow], int]:
    """Oldest first, so the longest-waiting rider is paid first."""
    conditions: list[ColumnElement[bool]] = []
    if status:
        try:
            conditions.append(RiderPayout.status == PayoutStatus(status.strip().upper()).value)
        except ValueError:
            raise ValidationError("status must be PROCESSING, COMPLETED or FAILED") from None
    if (rid := parse_uuid(rider_id, "rider_id")) is not None:
        conditions.append(RiderPayout.rider_id == rid)
    if q and q.strip():
        pattern = like_pattern(q.strip())
        conditions.append(or_(RiderPayout.reference.ilike(pattern), User.full_name.ilike(pattern)))
    start, end = day_window(date_from, date_to)
    if start:
        conditions.append(RiderPayout.created_at >= start)
    if end:
        conditions.append(RiderPayout.created_at < end)

    base = select(RiderPayout, User).join(User, User.id == RiderPayout.rider_id).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = await db.execute(base.order_by(RiderPayout.created_at.asc()).limit(limit).offset(offset))
    return [payout_row(p, u) for p, u in rows.all()], total


# ---------------------------------------------------------------------------
# Live tracking
# ---------------------------------------------------------------------------

LIVE_STATUSES = ("AVAILABLE", "HEADING_TO_PICKUP", "DELIVERING")


async def live_riders(db: AsyncSession, status: str | None = None) -> list[LiveRider]:
    """Every rider on shift, with where they are and what they carry.

    Positions come from Redis, the live source; a rider who has gone quiet
    shows with `has_live_location: false` rather than at a stale point.
    """
    if status and status.strip().upper() not in LIVE_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(LIVE_STATUSES)}")

    riders = (
        await db.execute(
            select(User, RiderProfile)
            .join(RiderProfile, RiderProfile.user_id == User.id)
            .where(RiderProfile.is_online.is_(True), User.is_active.is_(True))
            .order_by(User.full_name)
        )
    ).all()
    if not riders:
        return []

    customer = aliased(User)
    jobs = (
        await db.execute(
            select(Order, customer.full_name, Restaurant.name)
            .join(Restaurant, Restaurant.id == Order.restaurant_id)
            .outerjoin(customer, customer.id == Order.customer_id)
            .where(
                Order.rider_id.in_([u.id for u, _ in riders]),
                Order.status.in_([s.value for s in IN_FLIGHT]),
            )
            .order_by(Order.placed_at)
        )
    ).all()
    by_rider: dict[uuid.UUID, list] = {}
    for order, customer_name, restaurant_name in jobs:
        by_rider.setdefault(order.rider_id, []).append((order, customer_name, restaurant_name))

    out: list[LiveRider] = []
    for user, profile in riders:
        state = await get_rider_location(str(user.id))
        position = RiderPosition(**state) if state else None
        live = is_fresh(position) and position is not None
        held = by_rider.get(user.id, [])
        if any(str(o.status) == OrderStatus.PICKED_UP for o, _, _ in held):
            rider_status = "DELIVERING"
        elif held:
            rider_status = "HEADING_TO_PICKUP"
        else:
            rider_status = "AVAILABLE"
        if status and rider_status != status.strip().upper():
            continue
        out.append(
            LiveRider(
                id=str(user.id),
                full_name=user.full_name,
                phone=user.phone,
                avatar_url=user.avatar_url,
                vehicle_type=profile.vehicle_type,
                status=rider_status,
                latitude=position.latitude if live and position else None,
                longitude=position.longitude if live and position else None,
                location_updated_at=position.updated_at if position else None,
                has_live_location=live,
                orders=[
                    LiveOrderBrief(
                        order_id=str(o.id),
                        order_number=o.order_number,
                        status=str(o.status),
                        customer_name=customer_name,
                        restaurant_name=restaurant_name,
                        distance_to_dropoff_km=round(
                            haversine_km(
                                position.latitude,
                                position.longitude,
                                o.delivery_latitude,
                                o.delivery_longitude,
                            ),
                            2,
                        )
                        if live and position
                        else None,
                    )
                    for o, customer_name, restaurant_name in held
                ],
            )
        )
    return out
