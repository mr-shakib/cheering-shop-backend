"""The admin vendor screens: the roster, the profile tabs, and payouts by vendor.

A "vendor" here is a restaurant row: that is what customers order from and
what every money figure hangs off. The owner account and the partner
application are joined in for the Store Info tab, not the other way round.
Money figures use the per-order `commission_amount` snapshot (D6), never the
live rate — the same rule the vendor app's own earnings screen follows.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.money import to_major, to_minor
from app.models.enums import OrderStatus, PayoutStatus, UserRole, VendorApplicationStatus
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
from app.schemas.requests import AdminVendorCreateRequest, AdminVendorUpdateRequest
from app.services import email_service, platform_settings
from app.services.admin.common import (
    business_type_of,
    day_window,
    like_pattern,
    parse_uuid,
    validate_business_type,
)
from app.services.vendor import applications as vendor_applications
from app.services.vendor import finance as vendor_finance
from app.services.vendor import insights as vendor_insights
from app.services.vendor import storefront

log = structlog.get_logger()

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
    application = await _partner_record(db, r.id)

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
        onboarding_source=application.source if application else None,
        area=application.area if application else None,
        documents={k: str(v) for k, v in (application.documents or {}).items()}
        if application
        else {},
        payout=dict(application.payout or {}) if application else {},
    )


async def _partner_record(db: AsyncSession, restaurant_id: uuid.UUID) -> VendorApplication | None:
    """The vendor's application: where business type, NID and documents live."""
    return await db.scalar(
        select(VendorApplication)
        .where(VendorApplication.restaurant_id == restaurant_id)
        .order_by(VendorApplication.created_at.desc())
        .limit(1)
    )


# ---------------------------------------------------------------------------
# Add and edit (POST /admin/vendors, PATCH /admin/vendors/{id})
# ---------------------------------------------------------------------------


async def _check_identifier_free(
    db: AsyncSession, identifier: str, owner: User | None = None
) -> None:
    from app.services.auth_service import find_by_identifier

    holder = await find_by_identifier(db, identifier)
    if holder is not None and (owner is None or holder.id != owner.id):
        raise ConflictError(f"{identifier} already belongs to another account")


def _clean_cuisines(values: list[str]) -> list[str]:
    return [c.strip() for c in values if c.strip()]


async def create_vendor(
    db: AsyncSession, admin: User, body: AdminVendorCreateRequest
) -> AdminVendorDetail:
    """An owner account, its restaurant, and an ADMIN partner record, at once.

    The partner record is an application row with `source = ADMIN`: business
    type, category, NID and documents live there for every vendor, and this
    keeps Vendor Details complete for one added here. Approved at creation
    unless `is_verified` is false — then it waits in the application queue
    like any other.
    """
    email = body.owner_email.strip()
    phone = body.owner_phone.replace(" ", "")
    for identifier in (email, phone):
        await _check_identifier_free(db, identifier)

    owner = User(
        role=UserRole.VENDOR.value,
        email=email,
        phone=phone,
        full_name=body.owner_full_name.strip(),
        # The administrator typed them in; there is no code to redeem.
        is_email_verified=True,
        is_phone_verified=True,
    )
    db.add(owner)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("That email or phone already belongs to an account") from exc
    if body.owner_password:
        from app.services.auth_service import set_password

        await set_password(db, owner, body.owner_password)

    cuisines = _clean_cuisines(body.cuisine_types)
    restaurant = Restaurant(
        owner_id=owner.id,
        name=body.name.strip(),
        slug=await storefront._unique_slug(db, storefront.slugify(body.name)),
        description=body.description,
        phone=(body.phone or phone).replace(" ", ""),
        address_line=body.address_line,
        latitude=body.latitude,
        longitude=body.longitude,
        cuisine_types=cuisines,
        logo_url=body.logo_url,
        cover_image_url=body.cover_image_url,
        min_order_amount=to_minor(body.min_order_amount or 0),
        status=body.status,
        is_verified=body.is_verified,
        commission_rate=float(body.commission_rate)
        if body.commission_rate is not None
        else await platform_settings.default_commission_rate(db, body.business_type),
    )
    if body.avg_prep_time_mins is not None:
        restaurant.avg_prep_time_mins = body.avg_prep_time_mins
    db.add(restaurant)
    await db.flush()

    approved = body.is_verified
    db.add(
        VendorApplication(
            application_no=await vendor_applications._generate_application_no(db),
            user_id=owner.id,
            restaurant_id=restaurant.id,
            business_name=restaurant.name,
            business_type=body.business_type,
            business_category=body.business_category.strip(),
            branch_count=body.branch_count,
            cuisine_types=cuisines,
            address_line=body.address_line,
            area=body.area,
            latitude=body.latitude,
            longitude=body.longitude,
            owner_full_name=owner.full_name,
            owner_email=email,
            owner_phone=phone,
            national_id=body.national_id,
            documents=dict(body.documents),
            payout=body.payout.model_dump(exclude_none=True) if body.payout else {},
            agreed_to_terms=False,
            source="ADMIN",
            status=(
                VendorApplicationStatus.APPROVED if approved else VendorApplicationStatus.PENDING
            ).value,
            review_note="Added by an administrator" if approved else None,
            reviewed_by=admin.id if approved else None,
            reviewed_at=datetime.now(UTC) if approved else None,
        )
    )
    await db.flush()
    log.info(
        "vendor_created_by_admin",
        restaurant_id=str(restaurant.id),
        owner_id=str(owner.id),
        admin_id=str(admin.id),
        verified=approved,
    )
    if approved and not body.owner_password:
        # Same instructions an approved applicant gets: set a password with
        # the OTP reset flow. With a password, the administrator hands it over.
        await vendor_applications._notify(
            email, email_service.application_approved(restaurant.name, email)
        )
    return await get_vendor(db, restaurant.id)


_STORE_TEXT = ("description", "phone", "logo_url", "cover_image_url")
_BUSINESS = ("business_type", "business_category", "branch_count", "national_id",
             "documents", "payout", "area")


async def _apply_owner(db: AsyncSession, owner: User, fields: dict) -> None:
    if fields.get("owner_email"):
        email = fields["owner_email"].strip()
        await _check_identifier_free(db, email, owner)
        owner.email = email
        owner.is_email_verified = True
    if fields.get("owner_phone"):
        phone = fields["owner_phone"].replace(" ", "")
        await _check_identifier_free(db, phone, owner)
        owner.phone = phone
        owner.is_phone_verified = True
    if fields.get("owner_full_name"):
        owner.full_name = fields["owner_full_name"].strip()
    if fields.get("owner_password"):
        from app.services.auth_service import set_password

        await set_password(db, owner, fields["owner_password"])


async def _apply_store(
    db: AsyncSession, admin: User, r: Restaurant, body: AdminVendorUpdateRequest, fields: dict
) -> None:
    has_lat = fields.get("latitude") is not None
    has_lng = fields.get("longitude") is not None
    if has_lat != has_lng:
        raise ValidationError(
            "latitude and longitude must be updated together",
            details=["Send both coordinates, or neither"],
        )
    if has_lat:
        # `location` is generated from these, so discovery follows.
        r.latitude, r.longitude = fields["latitude"], fields["longitude"]
    if fields.get("name"):
        r.name = fields["name"].strip()
    if fields.get("address_line"):
        r.address_line = fields["address_line"]
    for name in _STORE_TEXT:
        if name in fields:
            setattr(r, name, fields[name])
    if fields.get("cuisine_types") is not None:
        r.cuisine_types = _clean_cuisines(fields["cuisine_types"])
    if fields.get("min_order_amount") is not None:
        r.min_order_amount = to_minor(fields["min_order_amount"])
    if fields.get("avg_prep_time_mins") is not None:
        r.avg_prep_time_mins = fields["avg_prep_time_mins"]
    if body.business_hours is not None:
        await storefront.set_hours(db, r, body.business_hours)
    if fields.get("commission_rate") is not None:
        r.commission_rate = float(fields["commission_rate"])
    if fields.get("is_active") is not None:
        r.is_active = fields["is_active"]
    if fields.get("status") is not None:
        r.status = fields["status"]
    if fields.get("is_verified") is not None and fields["is_verified"] != r.is_verified:
        if fields["is_verified"]:
            application = await _partner_record(db, r.id)
            if application is not None and application.status == VendorApplicationStatus.PENDING:
                # Approving here settles the application too, and sends the
                # owner the same sign-in instructions the queue would.
                await vendor_applications.approve(db, application.id, admin, None)
            r.is_verified = True
        else:
            # Suspending takes the store offline, as POST .../verify does.
            r.is_verified = False
            r.status = "CLOSED"


async def _apply_business(
    db: AsyncSession, admin: User, r: Restaurant, owner: User, fields: dict
) -> None:
    if not any(name in fields for name in _BUSINESS):
        return
    application = await _partner_record(db, r.id)
    if application is None:
        # A vendor from the one-call fast path has no partner record yet.
        if not owner.email:
            raise ValidationError(
                "This vendor has no owner email on file; send owner_email as well"
            )
        application = VendorApplication(
            application_no=await vendor_applications._generate_application_no(db),
            user_id=owner.id,
            restaurant_id=r.id,
            business_name=r.name,
            business_type="RESTAURANT",
            business_category="General",
            cuisine_types=list(r.cuisine_types or []),
            address_line=r.address_line or "",
            latitude=r.latitude,
            longitude=r.longitude,
            owner_full_name=owner.full_name or r.name,
            owner_email=owner.email,
            owner_phone=owner.phone or r.phone or "",
            agreed_to_terms=False,
            source="ADMIN",
            status=(
                VendorApplicationStatus.APPROVED
                if r.is_verified
                else VendorApplicationStatus.PENDING
            ).value,
            reviewed_by=admin.id if r.is_verified else None,
            reviewed_at=datetime.now(UTC) if r.is_verified else None,
        )
        db.add(application)
    for name in ("business_type", "business_category", "branch_count", "national_id", "area"):
        if fields.get(name) is not None:
            value = fields[name]
            setattr(application, name, value.strip() if isinstance(value, str) else value)
    if fields.get("documents") is not None:
        merged = dict(application.documents or {})
        for kind, url in fields["documents"].items():
            if url:
                merged[kind] = url
            else:
                merged.pop(kind, None)
        application.documents = merged
    if fields.get("payout") is not None:
        application.payout = {k: v for k, v in fields["payout"].items() if v is not None}


async def update_vendor(
    db: AsyncSession, admin: User, restaurant_id: uuid.UUID, body: AdminVendorUpdateRequest
) -> AdminVendorDetail:
    """Edit any vendor: the store, its owner's account, and its partner record.

    Identifier conflicts are checked before anything is written, and the
    request runs in one transaction, so a refused email leaves nothing
    half-applied.
    """
    r = await _get_restaurant(db, restaurant_id)
    owner = await db.get(User, r.owner_id)
    if owner is None:  # pragma: no cover — fk_restaurants_owner forbids it
        raise NotFoundError("This vendor's owner account is missing")
    fields = body.model_dump(exclude_unset=True)

    await _apply_owner(db, owner, fields)
    await _apply_store(db, admin, r, body, fields)
    await _apply_business(db, admin, r, owner, fields)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("That email or phone already belongs to an account") from exc

    log.info(
        "vendor_updated_by_admin",
        restaurant_id=str(r.id),
        admin_id=str(admin.id),
        fields=sorted(k for k in fields if k != "owner_password"),
    )
    return await get_vendor(db, r.id)


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
