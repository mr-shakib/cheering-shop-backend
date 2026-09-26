"""Read-only platform numbers: the Overview dashboard, Finance, global search.

Nothing here mutates. The rules match the vendor insights module:

* **Money counts DELIVERED orders only.** An order in flight or cancelled is
  not revenue, and counting it would make the dashboard disagree with every
  payout — the quickest way for the numbers to stop being believed.
* **Days are UTC**, grouped explicitly, so the same order lands on the same
  day whichever connection served the request.
* **Commission is the per-order snapshot** (D6), never the live rate.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ValidationError
from app.core.money import to_major
from app.models.enums import OrderStatus, RestaurantStatus, UserRole, VendorApplicationStatus
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.rider import RiderProfile
from app.models.rider_application import RiderApplication
from app.models.user import User
from app.schemas.admin import (
    AdminDashboard,
    AdminSearchResults,
    FinanceSummary,
    FinanceTransaction,
    Kpi,
    LiveOrderCounts,
    PendingApprovals,
    RevenuePoint,
    RevenueSeries,
    SearchHit,
    ServiceShare,
    SupportTicketCard,
)
from app.services import support
from app.services.admin.common import (
    business_type_of,
    day_window,
    like_pattern,
    order_number_from,
)
from app.services.admin.orders import recent_orders

_DELIVERED = OrderStatus.DELIVERED.value
_DELIVERED_DAY = cast(func.timezone("UTC", Order.delivered_at), Date)
_DELIVERED_MONTH = cast(func.date_trunc("month", func.timezone("UTC", Order.delivered_at)), Date)

RANGES = {"7d": 7, "30d": 30, "12m": 12}


def _kpi(value: int, previous: int, *, money: bool) -> Kpi:
    """A stat card. Money arrives in paisa and leaves in taka."""
    return Kpi(
        value=to_major(value) if money else Decimal(value),
        previous=to_major(previous) if money else Decimal(previous),
        change_pct=round((value - previous) * 100 / previous, 1) if previous else None,
    )


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


async def _gmv_between(db: AsyncSession, start: datetime, end: datetime) -> int:
    value = await db.scalar(
        select(func.coalesce(func.sum(Order.grand_total), 0)).where(
            Order.status == _DELIVERED, Order.delivered_at >= start, Order.delivered_at < end
        )
    )
    return int(value or 0)


async def _placed_between(db: AsyncSession, start: datetime, end: datetime) -> int:
    value = await db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.placed_at >= start, Order.placed_at < end)
    )
    return int(value or 0)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


async def dashboard(db: AsyncSession, recent_n: int = 8) -> AdminDashboard:
    """Today against yesterday, both whole UTC days. Yesterday is complete and
    today is not, so a morning view reads low — the cards say "vs yesterday",
    not "on pace"."""
    now = datetime.now(UTC)
    today = _midnight(now.date())
    yesterday = today - timedelta(days=1)

    live_rows = (
        await db.execute(
            select(Order.status, func.count())
            .where(
                Order.status.in_(
                    [
                        OrderStatus.PENDING.value,
                        OrderStatus.PREPARING.value,
                        OrderStatus.READY.value,
                        OrderStatus.PICKED_UP.value,
                    ]
                )
            )
            .group_by(Order.status)
        )
    ).all()
    live = {str(k): int(v) for k, v in live_rows}
    awaiting_rider = await db.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.rider_id.is_(None),
            Order.status.in_([OrderStatus.PREPARING.value, OrderStatus.READY.value]),
        )
    )
    cancelled_today = await db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.status == OrderStatus.CANCELLED.value, Order.cancelled_at >= today)
    )
    avg_seconds = await db.scalar(
        select(func.avg(func.extract("epoch", Order.delivered_at - Order.placed_at))).where(
            Order.status == _DELIVERED, Order.delivered_at >= today
        )
    )

    active_riders = await db.scalar(
        select(func.count())
        .select_from(RiderProfile)
        .join(User, User.id == RiderProfile.user_id)
        .where(RiderProfile.is_online.is_(True), User.is_active.is_(True))
    )
    online_vendors = await db.scalar(
        select(func.count())
        .select_from(Restaurant)
        .where(
            Restaurant.status == RestaurantStatus.OPEN.value,
            Restaurant.is_verified.is_(True),
            Restaurant.is_active.is_(True),
        )
    )
    # Same definition as GET /admin/restaurants/pending, so the card and the
    # queue it links to always show the same number.
    pending_vendors = await db.scalar(
        select(func.count()).select_from(Restaurant).where(Restaurant.is_verified.is_(False))
    )
    pending_riders = await db.scalar(
        select(func.count())
        .select_from(RiderApplication)
        .where(RiderApplication.status == VendorApplicationStatus.PENDING.value)
    )

    queue = await support.counts(db)

    return AdminDashboard(
        revenue_today=_kpi(
            await _gmv_between(db, today, now),
            await _gmv_between(db, yesterday, today),
            money=True,
        ),
        orders_today=_kpi(
            await _placed_between(db, today, now),
            await _placed_between(db, yesterday, today),
            money=False,
        ),
        active_riders=int(active_riders or 0),
        online_vendors=int(online_vendors or 0),
        pending_approvals=PendingApprovals(
            total=int(pending_vendors or 0) + int(pending_riders or 0),
            vendors=int(pending_vendors or 0),
            riders=int(pending_riders or 0),
        ),
        live_orders=LiveOrderCounts(
            new=live.get(OrderStatus.PENDING.value, 0),
            preparing=live.get(OrderStatus.PREPARING.value, 0)
            + live.get(OrderStatus.READY.value, 0),
            on_delivery=live.get(OrderStatus.PICKED_UP.value, 0),
            awaiting_rider=int(awaiting_rider or 0),
            cancelled_today=int(cancelled_today or 0),
            avg_delivery_minutes=round(float(avg_seconds) / 60) if avg_seconds else None,
        ),
        support_tickets=SupportTicketCard(
            open=queue.open + queue.pending, urgent=queue.urgent
        ),
        recent_orders=await recent_orders(db, recent_n),
        generated_at=now,
    )


async def revenue_series(db: AsyncSession, range_: str) -> RevenueSeries:
    """GMV per day (7d, 30d) or per month (12m), every bucket present.

    Empty days are zero-filled rather than omitted: a chart that skips a day
    with no sales draws a line straight across it and hides the dip.
    """
    if range_ not in RANGES:
        raise ValidationError("range must be one of: 7d, 30d, 12m")
    today = datetime.now(UTC).date()

    if range_ == "12m":
        first = date(today.year, today.month, 1)
        starts = []
        y, m = first.year, first.month
        for _ in range(12):
            starts.append(date(y, m, 1))
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        starts.reverse()
        bucket, granularity = _DELIVERED_MONTH, "month"
    else:
        days = RANGES[range_]
        starts = [today - timedelta(days=days - 1 - i) for i in range(days)]
        bucket, granularity = _DELIVERED_DAY, "day"

    result = await db.execute(
        select(bucket, func.coalesce(func.sum(Order.grand_total), 0), func.count())
        .where(Order.status == _DELIVERED, Order.delivered_at >= _midnight(starts[0]))
        .group_by(bucket)
    )
    by_start = {row[0]: (int(row[1]), int(row[2])) for row in result.all()}

    points = []
    for start in starts:
        gmv, orders = by_start.get(start, (0, 0))
        if granularity == "month":
            label = start.strftime("%b %Y")
        elif range_ == "7d":
            label = start.strftime("%a")
        else:
            label = f"{start.day} {start.strftime('%b')}"
        points.append(
            RevenuePoint(period_start=start, label=label, gmv=to_major(gmv), orders=orders)
        )
    return RevenueSeries(
        range=range_,
        granularity=granularity,
        total_gmv=sum((p.gmv for p in points), Decimal("0.00")),
        points=points,
    )


# ---------------------------------------------------------------------------
# Finance
# ---------------------------------------------------------------------------


async def _money_between(db: AsyncSession, start: datetime, end: datetime) -> dict[str, int]:
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Order.grand_total), 0),
                func.coalesce(func.sum(Order.commission_amount), 0),
                func.coalesce(func.sum(Order.delivery_fee), 0),
                func.coalesce(func.sum(Order.platform_fee), 0),
            ).where(
                Order.status == _DELIVERED, Order.delivered_at >= start, Order.delivered_at < end
            )
        )
    ).one()
    gmv, commission, delivery, platform = (int(v) for v in row)
    return {
        "gmv": gmv,
        "commission": commission,
        "delivery": delivery,
        "net": commission + platform,
    }


async def finance_summary(db: AsyncSession, days: int = 30) -> FinanceSummary:
    if not 1 <= days <= 366:
        raise ValidationError("days must be between 1 and 366")
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    before = start - timedelta(days=days)
    cur = await _money_between(db, start, now)
    prev = await _money_between(db, before, start)

    kind = func.coalesce(business_type_of(Order.restaurant_id), "UNKNOWN")
    shares = (
        await db.execute(
            select(kind, func.sum(Order.grand_total))
            .where(Order.status == _DELIVERED, Order.delivered_at >= start)
            .group_by(kind)
            .order_by(func.sum(Order.grand_total).desc())
        )
    ).all()
    total = sum(int(v) for _, v in shares)

    return FinanceSummary(
        days=days,
        gmv=_kpi(cur["gmv"], prev["gmv"], money=True),
        net_revenue=_kpi(cur["net"], prev["net"], money=True),
        commission_revenue=_kpi(cur["commission"], prev["commission"], money=True),
        delivery_revenue=_kpi(cur["delivery"], prev["delivery"], money=True),
        revenue_by_service=[
            ServiceShare(
                business_type=str(k),
                gmv=to_major(int(v)),
                share_pct=round(int(v) * 100 / total, 1) if total else 0.0,
            )
            for k, v in shares
        ],
    )


async def list_transactions(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
) -> tuple[list[FinanceTransaction], int]:
    """Delivered orders as money movements, newest first.

    There is no separate transactions ledger: a delivered order *is* the
    transaction, and `payment_reference` is the gateway's id for it. When a
    gateway lands and payments become their own rows, this is the one query
    that changes.
    """
    conditions: list[ColumnElement[bool]] = [Order.status == _DELIVERED]
    start, end = day_window(date_from, date_to)
    if start:
        conditions.append(Order.delivered_at >= start)
    if end:
        conditions.append(Order.delivered_at < end)
    if q and q.strip():
        pattern = like_pattern(q.strip())
        matches: list[ColumnElement[bool]] = [
            Restaurant.name.ilike(pattern),
            User.full_name.ilike(pattern),
            Order.payment_reference.ilike(pattern),
        ]
        number = order_number_from(q)
        if number is not None:
            matches.append(Order.order_number == number)
        conditions.append(or_(*matches))

    base = (
        select(Order, Restaurant.name, User.full_name)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .outerjoin(User, User.id == Order.customer_id)
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(base.order_by(Order.delivered_at.desc()).limit(limit).offset(offset))
    return [
        FinanceTransaction(
            order_id=str(o.id),
            order_number=o.order_number,
            payment_reference=o.payment_reference,
            payment_method=str(o.payment_method),
            payment_status=str(o.payment_status),
            restaurant_id=str(o.restaurant_id),
            restaurant_name=restaurant_name,
            customer_id=str(o.customer_id),
            customer_name=customer_name,
            amount=to_major(o.grand_total),
            commission_amount=to_major(o.commission_amount),
            delivered_at=o.delivered_at,
        )
        for o, restaurant_name, customer_name in result.all()
    ], total


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_HITS = 5


async def _people(db: AsyncSession, role: UserRole, pattern: str) -> list[SearchHit]:
    rows = await db.scalars(
        select(User)
        .where(
            User.role == role.value,
            or_(
                User.full_name.ilike(pattern), User.email.ilike(pattern), User.phone.ilike(pattern)
            ),
        )
        .order_by(User.full_name)
        .limit(_HITS)
    )
    return [
        SearchHit(
            id=str(u.id), title=u.full_name or u.email or u.phone or "", subtitle=u.phone or u.email
        )
        for u in rows.all()
    ]


async def search(db: AsyncSession, q: str) -> AdminSearchResults:
    """The top bar. Orders match by number only; people and vendors by name,
    phone or email. Two characters minimum — one matches half the platform."""
    query = q.strip()
    if len(query) < 2:
        raise ValidationError("Search needs at least 2 characters")
    pattern = like_pattern(query)

    orders: list[SearchHit] = []
    number = order_number_from(query)
    if number is not None:
        found = await db.execute(
            select(Order, Restaurant.name)
            .join(Restaurant, Restaurant.id == Order.restaurant_id)
            .where(Order.order_number == number)
        )
        orders = [
            SearchHit(id=str(o.id), title=f"ORD-{o.order_number}", subtitle=f"{name} · {o.status}")
            for o, name in found.all()
        ]

    vendors = await db.scalars(
        select(Restaurant)
        .where(or_(Restaurant.name.ilike(pattern), Restaurant.phone.ilike(pattern)))
        .order_by(Restaurant.name)
        .limit(_HITS)
    )
    return AdminSearchResults(
        query=query,
        orders=orders,
        customers=await _people(db, UserRole.CUSTOMER, pattern),
        vendors=[
            SearchHit(id=str(r.id), title=r.name, subtitle=r.address_line) for r in vendors.all()
        ],
        riders=await _people(db, UserRole.RIDER, pattern),
    )
