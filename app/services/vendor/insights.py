"""Read-only vendor numbers: analytics, dashboard, performance, reviews, CSV.

Split from `orders` (the state machine) because these never mutate anything —
every function here is a reporting query over rows the lifecycle module wrote.

* **D6** applies throughout: earnings always read the per-order
  `commission_amount` snapshot, never the live `restaurants.commission_rate`.
* Days are grouped in **UTC** explicitly, so the same order lands on the same
  day regardless of which connection served the request.
"""

from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.money import to_major
from app.models.enums import ActorType, OrderStatus
from app.models.order import Order, OrderItem
from app.models.restaurant import Restaurant
from app.models.review import Review
from app.models.user import User
from app.schemas.vendor import (
    AnalyticsDay,
    AnalyticsItem,
    AnalyticsTotals,
    DashboardDay,
    QueueCounts,
    RecentOrderRow,
    ReviewsSummary,
    VendorAnalytics,
    VendorDashboard,
    VendorPerformance,
    VendorReviewOut,
)
from app.services.vendor.orders import CHIP_TABS, QUEUE_TABS
from app.services.vendor.storefront import is_accepting_orders

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

# Grouping happens in UTC explicitly. Letting it fall through to the session
# timezone would make the same order land on different days depending on which
# connection served the request.
_DELIVERED_DAY = cast(func.timezone("UTC", Order.delivered_at), Date)


async def analytics(
    db: AsyncSession,
    restaurant: Restaurant,
    date_from: date | None,
    date_to: date | None,
    top_n: int = 10,
) -> VendorAnalytics:
    """Spec #43. Earnings over a window, from DELIVERED orders only.

    Served by the partial index
    ``ix_orders_analytics (restaurant_id, delivered_at) WHERE status = 'DELIVERED'``.

    Only delivered orders count. An in-flight or cancelled order is not revenue,
    and including it would make this dashboard disagree with every payout the
    vendor ever receives — which is the fastest way to lose their trust in the
    numbers. Cancellations are still visible, in `status_breakdown`.

    Money comes from `commission_amount` on each order, never from
    `restaurants.commission_rate` (decision D6): the rate is mutable, so reading
    it live would silently restate historical earnings the day it changed.
    """
    today = datetime.now(UTC).date()
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=29))
    if date_from > date_to:
        raise ValidationError("date_from must not be after date_to")

    # Half-open [start, end): the closed upper bound would otherwise drop
    # everything delivered after midnight on the final day.
    start = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=UTC)

    delivered = [
        Order.restaurant_id == restaurant.id,
        Order.status == OrderStatus.DELIVERED.value,
        Order.delivered_at >= start,
        Order.delivered_at < end,
    ]

    totals_row = (
        await db.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.item_total), 0),
                func.coalesce(func.sum(Order.commission_amount), 0),
                func.coalesce(func.sum(Order.grand_total), 0),
            ).where(*delivered)
        )
    ).one()
    order_count, gross, commission, grand = (
        int(totals_row[0]),
        int(totals_row[1]),
        int(totals_row[2]),
        int(totals_row[3]),
    )

    totals = AnalyticsTotals(
        orders=order_count,
        gross_sales=to_major(gross),
        commission=to_major(commission),
        net_payout=to_major(gross - commission),
        avg_order_value=to_major(round(grand / order_count) if order_count else 0),
    )

    daily_result = await db.execute(
        select(
            _DELIVERED_DAY.label("day"),
            func.count(Order.id),
            func.coalesce(func.sum(Order.item_total), 0),
            func.coalesce(func.sum(Order.commission_amount), 0),
        )
        .where(*delivered)
        .group_by(_DELIVERED_DAY)
        .order_by(_DELIVERED_DAY)
    )
    daily = [
        AnalyticsDay(
            date=row[0],
            orders=int(row[1]),
            gross_sales=to_major(int(row[2])),
            net_payout=to_major(int(row[2]) - int(row[3])),
        )
        for row in daily_result.all()
    ]

    top_result = await db.execute(
        select(
            OrderItem.menu_item_id,
            OrderItem.item_name,
            func.coalesce(func.sum(OrderItem.quantity), 0),
            func.coalesce(func.sum(OrderItem.line_total), 0),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*delivered)
        # Grouped by name as well as id so a deleted item (menu_item_id set to
        # NULL by the FK) still reports under the name it sold as, instead of
        # collapsing every removed dish into one anonymous row.
        .group_by(OrderItem.menu_item_id, OrderItem.item_name)
        .order_by(func.coalesce(func.sum(OrderItem.line_total), 0).desc())
        .limit(top_n)
    )
    top_items = [
        AnalyticsItem(
            menu_item_id=str(row[0]) if row[0] else None,
            name=row[1],
            quantity=int(row[2]),
            gross_sales=to_major(int(row[3])),
        )
        for row in top_result.all()
    ]

    # Placed, not delivered — otherwise cancelled orders could never appear,
    # since a cancelled order has no delivered_at by construction.
    breakdown_result = await db.execute(
        select(Order.status, func.count())
        .where(
            Order.restaurant_id == restaurant.id,
            Order.placed_at >= start,
            Order.placed_at < end,
        )
        .group_by(Order.status)
    )
    status_breakdown = {str(row[0]): int(row[1]) for row in breakdown_result.all()}

    return VendorAnalytics(
        restaurant_id=str(restaurant.id),
        date_from=date_from,
        date_to=date_to,
        totals=totals,
        daily=daily,
        top_items=top_items,
        status_breakdown=status_breakdown,
    )


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


async def list_reviews(
    db: AsyncSession, restaurant: Restaurant, limit: int, offset: int
) -> tuple[list[VendorReviewOut], int]:
    """[EXTENDED] What customers said, newest first.

    Served by `ix_reviews_restaurant (restaurant_id, created_at DESC)`. Only the
    restaurant rating and comment are exposed — `rider_rating` is about the
    delivery, and showing a vendor a score they cannot influence invites
    complaints they cannot act on.
    """
    conditions = [Review.restaurant_id == restaurant.id]
    total = await db.scalar(select(func.count()).select_from(Review).where(*conditions)) or 0

    result = await db.execute(
        select(Review, Order.order_number, User.full_name)
        .join(Order, Order.id == Review.order_id, isouter=True)
        .join(User, User.id == Review.customer_id, isouter=True)
        .where(*conditions)
        .order_by(Review.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    reviews = [
        VendorReviewOut(
            id=str(review.id),
            order_id=str(review.order_id),
            order_number=order_number,
            restaurant_rating=review.restaurant_rating,
            comment=review.comment,
            customer_name=full_name,
            created_at=review.created_at,
        )
        for review, order_number, full_name in result.all()
    ]
    return reviews, total


async def reviews_summary(db: AsyncSession, restaurant: Restaurant) -> ReviewsSummary:
    """[EXTENDED] The Feedback header: average, count, and the star bars.

    Recomputed from the rows rather than read from `restaurants.rating_avg`:
    the denormalised figure is worker-maintained and the histogram must sum to
    the count shown beside it, or the bars visibly lie.
    """
    result = await db.execute(
        select(Review.restaurant_rating, func.count())
        .where(Review.restaurant_id == restaurant.id)
        .group_by(Review.restaurant_rating)
    )
    histogram = {star: 0 for star in range(1, 6)}
    for rating, count in result.all():
        histogram[int(rating)] = int(count)

    total = sum(histogram.values())
    avg = (
        round(sum(star * count for star, count in histogram.items()) / total, 1)
        if total
        else 0.0
    )
    return ReviewsSummary(
        restaurant_id=str(restaurant.id),
        rating_avg=avg,
        rating_count=total,
        histogram=histogram,
    )


# ---------------------------------------------------------------------------
# Dashboard & performance
# ---------------------------------------------------------------------------


async def _acceptance_rate(
    db: AsyncSession, restaurant: Restaurant, since: datetime
) -> float | None:
    """Accepted / decided since `since`.

    The denominator counts only orders the VENDOR decided (or ran out the
    clock on): accepted, plus cancellations by VENDOR or SYSTEM while still
    unaccepted. A customer cancelling their own PENDING order says nothing
    about the kitchen and would dilute the rate.
    """
    row = (
        await db.execute(
            select(
                func.count(Order.id).filter(Order.accepted_at.isnot(None)),
                func.count(Order.id).filter(
                    Order.accepted_at.is_(None),
                    Order.status == OrderStatus.CANCELLED.value,
                    Order.cancelled_by.in_([ActorType.VENDOR.value, ActorType.SYSTEM.value]),
                ),
            ).where(Order.restaurant_id == restaurant.id, Order.placed_at >= since)
        )
    ).one()
    accepted, declined = int(row[0]), int(row[1])
    decided = accepted + declined
    return round(accepted / decided, 4) if decided else None


async def dashboard(db: AsyncSession, restaurant: Restaurant) -> VendorDashboard:
    """[EXTENDED] One call for the Order tab header and the Overview tab.

    Assembled from the same queries the dedicated endpoints use, so the
    numbers here can never disagree with the screens behind them. Days are
    UTC, matching analytics.
    """
    now = datetime.now(UTC)
    today_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)

    # One grouped count behind all three chips. It counts the same QUEUE_TABS
    # groups the queue itself filters on, so New(5) is precisely what
    # `?status=NEW` lists — chips and list cannot drift apart.
    chip_statuses = {s for tab in CHIP_TABS for s in QUEUE_TABS[tab]}
    status_rows = await db.execute(
        select(Order.status, func.count())
        .where(
            Order.restaurant_id == restaurant.id,
            Order.status.in_([s.value for s in chip_statuses]),
        )
        .group_by(Order.status)
    )
    by_status = {str(s): int(c) for s, c in status_rows.all()}

    def chip(tab: str) -> int:
        return sum(by_status.get(s, 0) for s in QUEUE_TABS[tab])

    today_row = (
        await db.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.item_total - Order.commission_amount), 0),
            ).where(
                Order.restaurant_id == restaurant.id,
                Order.status == OrderStatus.DELIVERED.value,
                Order.delivered_at >= today_start,
            )
        )
    ).one()
    today_orders, today_earnings = int(today_row[0]), int(today_row[1])

    week_start = today_start - timedelta(days=6)
    week_rows = await db.execute(
        select(
            _DELIVERED_DAY.label("day"),
            func.count(Order.id),
            func.coalesce(func.sum(Order.item_total - Order.commission_amount), 0),
        )
        .where(
            Order.restaurant_id == restaurant.id,
            Order.status == OrderStatus.DELIVERED.value,
            Order.delivered_at >= week_start,
        )
        .group_by(_DELIVERED_DAY)
    )
    by_day = {row[0]: (int(row[1]), int(row[2])) for row in week_rows.all()}
    last_7_days = [
        DashboardDay(
            date=d,
            orders=by_day.get(d, (0, 0))[0],
            earnings=to_major(by_day.get(d, (0, 0))[1]),
        )
        for d in (now.date() - timedelta(days=offset) for offset in range(6, -1, -1))
    ]

    recent_result = await db.execute(
        select(Order, User.full_name)
        .join(User, User.id == Order.customer_id, isouter=True)
        .where(Order.restaurant_id == restaurant.id)
        .order_by(Order.placed_at.desc())
        .limit(5)
    )
    recent_orders = [
        RecentOrderRow(
            id=str(o.id),
            order_number=o.order_number,
            status=str(o.status),
            customer_name=full_name,
            grand_total=to_major(o.grand_total),
            placed_at=o.placed_at,
        )
        for o, full_name in recent_result.all()
    ]

    return VendorDashboard(
        restaurant_id=str(restaurant.id),
        store_status=str(restaurant.status),
        is_accepting_orders=is_accepting_orders(restaurant),
        queue=QueueCounts(
            new=chip("NEW"),
            preparing=chip("PREPARING"),
            complete=chip("COMPLETE"),
            ready=by_status.get(OrderStatus.READY, 0),
            completed_today=today_orders,
        ),
        today_orders=today_orders,
        today_earnings=to_major(today_earnings),
        rating_avg=float(restaurant.rating_avg),
        rating_count=restaurant.rating_count,
        acceptance_rate=await _acceptance_rate(db, restaurant, now - timedelta(days=30)),
        last_7_days=last_7_days,
        recent_orders=recent_orders,
    )


async def performance(
    db: AsyncSession, restaurant: Restaurant, window_days: int = 30
) -> VendorPerformance:
    """[EXTENDED] The Performance & ratings screen.

    On-time uses the only promise the schema records: the restaurant's own
    `avg_prep_time_mins`. An order is on time when READY within that many
    minutes of acceptance. Null rates mean "no data yet", never zero — a new
    vendor has not failed at anything.
    """
    now = datetime.now(UTC)
    since = now - timedelta(days=window_days)

    prep_row = (
        await db.execute(
            select(
                func.count(Order.id),
                func.count(Order.id).filter(
                    Order.ready_at - Order.accepted_at
                    <= timedelta(minutes=restaurant.avg_prep_time_mins)
                ),
            ).where(
                Order.restaurant_id == restaurant.id,
                Order.placed_at >= since,
                Order.accepted_at.isnot(None),
                Order.ready_at.isnot(None),
            )
        )
    ).one()
    prepared, on_time = int(prep_row[0]), int(prep_row[1])

    rejections = await db.scalar(
        select(func.count(Order.id)).where(
            Order.restaurant_id == restaurant.id,
            Order.status == OrderStatus.CANCELLED.value,
            Order.cancelled_by == ActorType.VENDOR.value,
            Order.cancelled_at >= now - timedelta(days=7),
        )
    )

    return VendorPerformance(
        restaurant_id=str(restaurant.id),
        window_days=window_days,
        acceptance_rate=await _acceptance_rate(db, restaurant, since),
        on_time_rate=round(on_time / prepared, 4) if prepared else None,
        rating_avg=float(restaurant.rating_avg),
        rating_count=restaurant.rating_count,
        rejections_this_week=int(rejections or 0),
    )


# ---------------------------------------------------------------------------
# Report export
# ---------------------------------------------------------------------------


async def report_csv(
    db: AsyncSession, restaurant: Restaurant, date_from: date | None, date_to: date | None
) -> tuple[str, str]:
    """[EXTENDED] The Report screen's "All CSV Download".

    Returns `(filename, csv_text)`. One row per DELIVERED order in the window
    — the same population as `/vendor/analytics`, so the spreadsheet's sums
    match the tiles above the button. Money in whole taka, like the API.
    """
    import csv as csv_module
    import io

    today = datetime.now(UTC).date()
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=29))
    if date_from > date_to:
        raise ValidationError("date_from must not be after date_to")

    start = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=UTC)

    result = await db.execute(
        select(Order)
        .where(
            Order.restaurant_id == restaurant.id,
            Order.status == OrderStatus.DELIVERED.value,
            Order.delivered_at >= start,
            Order.delivered_at < end,
        )
        .order_by(Order.delivered_at.asc())
    )

    buffer = io.StringIO()
    writer = csv_module.writer(buffer)
    writer.writerow(
        [
            "order_number",
            "delivered_at_utc",
            "payment_method",
            "item_total",
            "delivery_fee",
            "grand_total",
            "commission",
            "vendor_payout",
        ]
    )
    for order in result.scalars().all():
        # delivered_at cannot be NULL on a DELIVERED row (ck_orders_delivered),
        # but the type is Optional — hence the guard.
        delivered = order.delivered_at
        writer.writerow(
            [
                order.order_number,
                delivered.astimezone(UTC).isoformat() if delivered else "",
                str(order.payment_method),
                to_major(order.item_total),
                to_major(order.delivery_fee),
                to_major(order.grand_total),
                to_major(order.commission_amount),
                to_major(order.item_total - order.commission_amount),
            ]
        )

    filename = f"report_{restaurant.slug}_{date_from}_{date_to}.csv"
    return filename, buffer.getvalue()
