"""Vendor promotions — the Promotions screens, built on `promo_codes`.

A vendor promotion IS a restaurant-scoped promo code with an auto-generated
code. Reusing the table means checkout, when it lands, applies vendor offers
and platform codes through one mechanism, one redemption ledger and one
per-user limit — a parallel `vendor_promotions` table would need all of that
duplicated and then reconciled.

**Storage units** (inherited from the table): PERCENTAGE in basis points
(1500 == 15%), FLAT (stored as FIXED) in paisa, FREE_DELIVERY as value 0.
The API converts at the edge like everywhere else — percent and whole taka.

**Redemption is not implemented here.** Checkout is still 501, so
`redemptions`/`budget_spent` read zero until it ships. The contract they are
read through exists now so the app can build against it; the budget-cap rule
(refuse once spent >= cap) is checkout's to enforce and is recorded on the row.
"""

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.money import to_major, to_minor
from app.models.enums import DiscountType
from app.models.menu import MenuItem
from app.models.order import Order
from app.models.promo import PromoCode, PromoRedemption
from app.models.restaurant import Restaurant
from app.schemas.requests import PromotionCreateRequest, PromotionUpdateRequest
from app.schemas.vendor import PromotionDay, PromotionDetail, PromotionOut

log = structlog.get_logger()


def _title(promo: PromoCode) -> str:
    """The card label: "20% OFF", "৳50 OFF", "Free delivery"."""
    kind = str(promo.discount_type)
    if kind == DiscountType.PERCENTAGE:
        return f"{promo.discount_value // 100}% OFF"
    if kind == DiscountType.FIXED:
        return f"৳{to_major(promo.discount_value)} OFF"
    return "Free delivery"


def _state(promo: PromoCode) -> str:
    """One word for the card: SCHEDULED, ACTIVE, PAUSED or ENDED."""
    now = datetime.now(UTC)
    if promo.valid_until <= now:
        return "ENDED"
    if not promo.is_active:
        return "PAUSED"
    if promo.valid_from > now:
        return "SCHEDULED"
    return "ACTIVE"


async def _generate_code(db: AsyncSession, restaurant: Restaurant) -> str:
    """Unique, typeable code derived from the storefront, e.g. ``KFC-8231``.

    Auto-generated because the form never asks for one, but real because
    checkout redeems promotions by code — and a vendor can put it on a flyer.
    """
    stem = "".join(c for c in restaurant.slug.upper() if c.isalnum())[:8] or "OFFER"
    for _ in range(20):
        candidate = f"{stem}-{secrets.randbelow(9000) + 1000}"
        exists = await db.scalar(
            select(func.count()).select_from(PromoCode).where(PromoCode.code == candidate)
        )
        if not exists:
            return candidate
    return f"{stem}-{secrets.randbelow(900000) + 100000}"  # pragma: no cover


async def _validate_item_ids(
    db: AsyncSession, restaurant: Restaurant, item_ids: list
) -> list:
    """Every id must be a live item on THIS vendor's menu — a foreign id would
    let one vendor advertise a discount that silently never applies."""
    unique_ids = list(dict.fromkeys(item_ids))
    result = await db.execute(
        select(MenuItem.id).where(
            MenuItem.restaurant_id == restaurant.id,
            MenuItem.id.in_(unique_ids),
            MenuItem.deleted_at.is_(None),
        )
    )
    found = {row[0] for row in result.all()}
    missing = [str(i) for i in unique_ids if i not in found]
    if missing:
        raise ValidationError(
            "Some items do not exist on your menu", details=missing[:10]
        )
    return unique_ids


async def create(
    db: AsyncSession, restaurant: Restaurant, body: PromotionCreateRequest
) -> PromoCode:
    """POST /vendor/promotions — Launch Promotion."""
    starts_at = body.starts_at or datetime.now(UTC)
    if body.ends_at <= starts_at:
        raise ValidationError("end date must be after the start date")

    kind = body.discount_type
    if kind == "FREE_DELIVERY":
        if body.discount_value is not None:
            raise ValidationError("FREE_DELIVERY takes no discount_value")
        stored_type, stored_value = DiscountType.FREE_DELIVERY.value, 0
    elif kind == "PERCENTAGE":
        if body.discount_value is None or not (1 <= body.discount_value <= 100):
            raise ValidationError("PERCENTAGE needs a discount_value between 1 and 100")
        stored_type = DiscountType.PERCENTAGE.value
        stored_value = int(body.discount_value * 100)  # percent -> basis points
    else:  # FLAT — stored under the table's FIXED type
        if body.discount_value is None:
            raise ValidationError("FLAT needs a discount_value in taka")
        stored_type, stored_value = DiscountType.FIXED.value, to_minor(body.discount_value)

    item_ids = None
    if body.item_ids:
        item_ids = await _validate_item_ids(db, restaurant, body.item_ids)

    promo = PromoCode(
        code=await _generate_code(db, restaurant),
        description=None,
        discount_type=stored_type,
        discount_value=stored_value,
        max_discount=to_minor(body.max_discount) if body.max_discount else None,
        min_order_amount=to_minor(body.min_order_amount),
        restaurant_id=restaurant.id,
        valid_from=starts_at,
        valid_until=body.ends_at,
        budget_cap=to_minor(body.budget_cap) if body.budget_cap else None,
        applies_to_item_ids=item_ids,
    )
    db.add(promo)
    await db.flush()

    log.info(
        "promotion_created",
        promo_id=str(promo.id),
        restaurant_id=str(restaurant.id),
        code=promo.code,
        type=stored_type,
    )
    return promo


async def _get_owned(db: AsyncSession, restaurant: Restaurant, promo_id) -> PromoCode:
    """404 for missing AND for someone else's — same convention as orders."""
    promo = await db.get(PromoCode, promo_id)
    if promo is None or promo.restaurant_id != restaurant.id:
        raise NotFoundError("Promotion not found")
    return promo


async def _stats(db: AsyncSession, promo_ids: list) -> dict:
    """{promo_id: (redemptions, spent_minor, revenue_minor)} in one query."""
    if not promo_ids:
        return {}
    result = await db.execute(
        select(
            PromoRedemption.promo_code_id,
            func.count(PromoRedemption.id),
            func.coalesce(func.sum(PromoRedemption.discount_applied), 0),
            func.coalesce(func.sum(Order.grand_total), 0),
        )
        .join(Order, Order.id == PromoRedemption.order_id)
        .where(PromoRedemption.promo_code_id.in_(promo_ids))
        .group_by(PromoRedemption.promo_code_id)
    )
    return {row[0]: (int(row[1]), int(row[2]), int(row[3])) for row in result.all()}


async def list_promotions(db: AsyncSession, restaurant: Restaurant) -> list[PromotionOut]:
    """All of this vendor's promotions, newest first. Unpaginated: a single
    storefront runs a handful of offers, not thousands."""
    result = await db.execute(
        select(PromoCode)
        .where(PromoCode.restaurant_id == restaurant.id)
        .order_by(PromoCode.created_at.desc())
    )
    promos = list(result.scalars().all())
    stats = await _stats(db, [p.id for p in promos])
    return [to_out(p, *stats.get(p.id, (0, 0, 0))) for p in promos]


async def get_detail(db: AsyncSession, restaurant: Restaurant, promo_id) -> PromotionDetail:
    """GET /vendor/promotions/{id} — the card stats plus the 7-day chart."""
    promo = await _get_owned(db, restaurant, promo_id)
    stats = await _stats(db, [promo.id])

    today = datetime.now(UTC).date()
    window_start = datetime.combine(today - timedelta(days=6), datetime.min.time(), tzinfo=UTC)
    day_col = cast(func.timezone("UTC", PromoRedemption.created_at), Date)
    daily_result = await db.execute(
        select(day_col, func.count(PromoRedemption.id))
        .where(
            PromoRedemption.promo_code_id == promo.id,
            PromoRedemption.created_at >= window_start,
        )
        .group_by(day_col)
    )
    by_day = {row[0]: int(row[1]) for row in daily_result.all()}
    last_7_days = [
        PromotionDay(date=d, redemptions=by_day.get(d, 0))
        for d in (today - timedelta(days=offset) for offset in range(6, -1, -1))
    ]

    base = to_out(promo, *stats.get(promo.id, (0, 0, 0)))
    return PromotionDetail(**base.model_dump(), last_7_days=last_7_days)


async def update(
    db: AsyncSession, restaurant: Restaurant, promo_id, body: PromotionUpdateRequest
) -> PromoCode:
    """PATCH /vendor/promotions/{id} — pause/resume, or end early (final)."""
    promo = await _get_owned(db, restaurant, promo_id)
    now = datetime.now(UTC)

    if promo.valid_until <= now:
        raise ValidationError("This promotion has ended and can no longer be changed")

    if body.end_now:
        promo.valid_until = now
        log.info("promotion_ended_early", promo_id=str(promo.id))
    elif body.is_active is not None:
        promo.is_active = body.is_active
        log.info("promotion_toggled", promo_id=str(promo.id), is_active=body.is_active)
    else:
        raise ValidationError("Nothing to change: send is_active or end_now")

    await db.flush()
    return promo


def to_out(
    promo: PromoCode, redemptions: int, spent_minor: int, revenue_minor: int
) -> PromotionOut:
    kind = str(promo.discount_type)
    if kind == DiscountType.PERCENTAGE:
        display_value: Decimal | None = Decimal(promo.discount_value) / 100
    elif kind == DiscountType.FIXED:
        display_value = to_major(promo.discount_value)
    else:
        display_value = None

    return PromotionOut(
        id=str(promo.id),
        restaurant_id=str(promo.restaurant_id),
        code=promo.code,
        title=_title(promo),
        discount_type="FLAT" if kind == DiscountType.FIXED else kind,
        discount_value=display_value,
        max_discount=to_major(promo.max_discount) if promo.max_discount else None,
        min_order_amount=to_major(promo.min_order_amount),
        applies_to_all_items=not promo.applies_to_item_ids,
        item_ids=[str(i) for i in (promo.applies_to_item_ids or [])],
        starts_at=promo.valid_from,
        ends_at=promo.valid_until,
        budget_cap=to_major(promo.budget_cap) if promo.budget_cap else None,
        budget_spent=to_major(spent_minor),
        redemptions=redemptions,
        revenue_generated=to_major(revenue_minor),
        state=_state(promo),
        is_active=promo.is_active,
        created_at=promo.created_at,
    )
