"""The admin vendor screens: the roster, the profile tabs, and payouts by vendor.

A "vendor" here is a restaurant row: that is what customers order from and
what every money figure hangs off. The owner account and the partner
application are joined in for the Store Info tab, not the other way round.
Money figures use the per-order `commission_amount` snapshot (D6), never the
live rate — the same rule the vendor app's own earnings screen follows.
"""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import NotFoundError, ValidationError
from app.core.money import to_major
from app.models.enums import OrderStatus, PayoutStatus
from app.models.menu import MenuItem
from app.models.order import Order
from app.models.payout import VendorPayout
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.vendor_application import VendorApplication
from app.schemas.admin import (
    AdminPayoutRow,
    AdminVendorDetail,
    AdminVendorFinance,
    AdminVendorOwner,
    AdminVendorReviews,
    AdminVendorRow,
)
from app.services.admin.common import (
    business_type_of,
    day_window,
    like_pattern,
    parse_uuid,
    validate_business_type,
)
from app.services.vendor import finance as vendor_finance
from app.services.vendor import insights as vendor_insights

_DELIVERED = OrderStatus.DELIVERED.value

# The Active Vendors screen is verified storefronts. The others are for the
# same table filtered differently: suspended ones, or everything.
_STATUSES = {"ACTIVE", "SUSPENDED", "ALL"}


def _order_stats():
    return (
        select(
            Order.restaurant_id.label("restaurant_id"),
            func.count().label("orders"),
            func.coalesce(func.sum(Order.item_total), 0).label("revenue"),
        )
        .where(Order.status == _DELIVERED)
        .group_by(Order.restaurant_id)
        .subquery()
    )


def _product_counts():
    return (
        select(MenuItem.restaurant_id.label("restaurant_id"), func.count().label("n"))
        .where(MenuItem.deleted_at.is_(None))
        .group_by(MenuItem.restaurant_id)
        .subquery()
    )


def _to_row(
    r: Restaurant, business_type: str | None, orders: int, revenue: int, products: int
) -> AdminVendorRow:
    return AdminVendorRow(
        id=str(r.id),
        name=r.name,
        logo_url=r.logo_url,
        business_type=business_type,
        phone=r.phone,
        order_count=orders,
        revenue=to_major(revenue),
        rating_avg=float(r.rating_avg),
        rating_count=r.rating_count,
        product_count=products,
        status=str(r.status),
        is_verified=r.is_verified,
        is_active=r.is_active,
        created_at=r.created_at,
    )


async def list_vendors(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = "ACTIVE",
    q: str | None = None,
    business_type: str | None = None,
    min_rating: float | None = None,
) -> tuple[list[AdminVendorRow], int]:
    """Highest revenue first — the vendors an operator most needs to find."""
    wanted = (status or "ALL").strip().upper()
    if wanted not in _STATUSES:
        raise ValidationError("status must be ACTIVE, SUSPENDED or ALL")

    stats = _order_stats()
    products = _product_counts()
    type_expr = business_type_of(Restaurant.id)
    conditions: list[ColumnElement[bool]] = []
    if wanted == "ACTIVE":
        conditions += [Restaurant.is_verified.is_(True), Restaurant.is_active.is_(True)]
    elif wanted == "SUSPENDED":
        conditions.append(or_(Restaurant.is_verified.is_(False), Restaurant.is_active.is_(False)))
    if q and q.strip():
        pattern = like_pattern(q.strip())
        conditions.append(or_(Restaurant.name.ilike(pattern), Restaurant.phone.ilike(pattern)))
    if (kind := validate_business_type(business_type)) is not None:
        conditions.append(type_expr == kind)
    if min_rating is not None:
        conditions.append(Restaurant.rating_avg >= min_rating)

    total = await db.scalar(select(func.count()).select_from(Restaurant).where(*conditions)) or 0
    revenue = func.coalesce(stats.c.revenue, 0)
    result = await db.execute(
        select(
            Restaurant,
            type_expr,
            func.coalesce(stats.c.orders, 0),
            revenue,
            func.coalesce(products.c.n, 0),
        )
        .outerjoin(stats, stats.c.restaurant_id == Restaurant.id)
        .outerjoin(products, products.c.restaurant_id == Restaurant.id)
        .where(*conditions)
        .order_by(revenue.desc(), Restaurant.name)
        .limit(limit)
        .offset(offset)
    )
    return [
        _to_row(r, kind, int(n), int(rev), int(p)) for r, kind, n, rev, p in result.all()
    ], total


async def _get_restaurant(db: AsyncSession, restaurant_id: uuid.UUID) -> Restaurant:
    restaurant = await db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("No vendor with that id")
    return restaurant


async def get_vendor(db: AsyncSession, restaurant_id: uuid.UUID) -> AdminVendorDetail:
    r = await _get_restaurant(db, restaurant_id)
    orders, revenue = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.item_total), 0)).where(
                Order.restaurant_id == r.id, Order.status == _DELIVERED
            )
        )
    ).one()
    product_count = await db.scalar(
        select(func.count())
        .select_from(MenuItem)
        .where(MenuItem.restaurant_id == r.id, MenuItem.deleted_at.is_(None))
    )
    owner = await db.get(User, r.owner_id)
    application = await db.scalar(
        select(VendorApplication)
        .where(VendorApplication.restaurant_id == r.id)
        .order_by(VendorApplication.created_at.desc())
        .limit(1)
    )

    row = _to_row(
        r,
        application.business_type if application else None,
        int(orders),
        int(revenue),
        int(product_count or 0),
    )
    return AdminVendorDetail(
        **row.model_dump(),
        slug=r.slug,
        description=r.description,
        cover_image_url=r.cover_image_url,
        cuisine_types=list(r.cuisine_types or []),
        business_category=application.business_category if application else None,
        address_line=r.address_line,
        latitude=r.latitude,
        longitude=r.longitude,
        owner=AdminVendorOwner(
            id=str(r.owner_id),
            full_name=owner.full_name if owner else None,
            email=owner.email if owner else None,
            phone=owner.phone if owner else None,
            national_id=application.national_id if application else None,
        ),
        business_hours=r.business_hours,
        avg_prep_time_mins=r.avg_prep_time_mins,
        min_order_amount=to_major(r.min_order_amount),
        delivery_fee_base=to_major(r.delivery_fee_base),
        commission_rate=float(r.commission_rate),
        application_id=str(application.id) if application else None,
        application_no=application.application_no if application else None,
        documents={k: str(v) for k, v in (application.documents or {}).items()}
        if application
        else {},
    )


async def get_reviews(
    db: AsyncSession, restaurant_id: uuid.UUID, limit: int, offset: int
) -> tuple[AdminVendorReviews, int]:
    """The vendor app's own review queries, pointed at any restaurant."""
    r = await _get_restaurant(db, restaurant_id)
    summary = await vendor_insights.reviews_summary(db, r)
    reviews, total = await vendor_insights.list_reviews(db, r, limit, offset)
    return AdminVendorReviews(summary=summary, reviews=reviews), total


async def get_finance(db: AsyncSession, restaurant_id: uuid.UUID) -> AdminVendorFinance:
    r = await _get_restaurant(db, restaurant_id)
    earned_gross, commission = (
        await db.execute(
            select(
                func.coalesce(func.sum(Order.item_total), 0),
                func.coalesce(func.sum(Order.commission_amount), 0),
            ).where(Order.restaurant_id == r.id, Order.status == _DELIVERED)
        )
    ).one()
    balance = await vendor_finance.earnings(db, r, recent_n=0)
    return AdminVendorFinance(
        restaurant_id=str(r.id),
        total_earning=to_major(int(earned_gross)),
        total_commission=to_major(int(commission)),
        total_payout=balance.total_withdrawn,
        pending_amount=balance.processing_payouts,
        available_balance=balance.available_balance,
    )


# ---------------------------------------------------------------------------
# Payout queue (GET /admin/payouts)
# ---------------------------------------------------------------------------


def to_payout_row(payout: VendorPayout, restaurant_name: str) -> AdminPayoutRow:
    return AdminPayoutRow(
        **vendor_finance.to_out(payout).model_dump(),
        restaurant_name=restaurant_name,
        reopened_at=payout.reopened_at,
        reopen_reason=payout.reopen_reason,
    )


async def reopen_payout(
    db: AsyncSession, payout_id: uuid.UUID, admin: User, reason: str
) -> AdminPayoutRow:
    payout = await vendor_finance.admin_reopen(db, payout_id, admin, reason)
    restaurant = await db.get(Restaurant, payout.restaurant_id)
    return to_payout_row(payout, restaurant.name if restaurant else "")


async def list_payouts(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None,
    restaurant_id: str | None = None,
    q: str | None = None,
    date_from=None,
    date_to=None,
) -> tuple[list[AdminPayoutRow], int]:
    """The transfer queue, oldest first so the longest-waiting vendor is paid
    first. Filters narrow it to one vendor (the Withdrawal tab), a reference
    or vendor name, or the requested-on date range."""
    conditions: list[ColumnElement[bool]] = []
    if status:
        try:
            conditions.append(VendorPayout.status == PayoutStatus(status.strip().upper()).value)
        except ValueError:
            valid = ", ".join(s.value for s in PayoutStatus)
            raise ValidationError(f"Unknown status. Valid values: {valid}") from None
    parsed = parse_uuid(restaurant_id, "restaurant_id")
    if parsed:
        conditions.append(VendorPayout.restaurant_id == parsed)
    if q and q.strip():
        pattern = like_pattern(q.strip())
        conditions.append(
            or_(VendorPayout.reference.ilike(pattern), Restaurant.name.ilike(pattern))
        )
    start, end = day_window(date_from, date_to)
    if start:
        conditions.append(VendorPayout.created_at >= start)
    if end:
        conditions.append(VendorPayout.created_at < end)

    base = (
        select(VendorPayout, Restaurant.name)
        .join(Restaurant, Restaurant.id == VendorPayout.restaurant_id)
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(VendorPayout.created_at.asc()).limit(limit).offset(offset)
    )
    return [to_payout_row(p, name) for p, name in result.all()], total
