"""The Advertisement screen, and the impression and click counters behind it.

A "campaign" is a vendor promotion: the offer the home feed's promoted row
advertises. Labels, states and money figures come from the vendor promotions
module, so the console and the vendor app never disagree about a campaign.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import NotFoundError, ValidationError
from app.core.money import to_major
from app.models.promo import PromoCode
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.admin import AdCampaignOut
from app.schemas.requests import PromotionEventsRequest
from app.services.admin.common import like_pattern, parse_uuid
from app.services.vendor import promotions

log = structlog.get_logger()

STATUSES = ("SCHEDULED", "ACTIVE", "PAUSED", "ENDED")


def _to_out(promo: PromoCode, restaurant_name: str, figures: tuple[int, int, int]) -> AdCampaignOut:
    redemptions, spent, revenue = figures
    return AdCampaignOut(
        id=str(promo.id),
        restaurant_id=str(promo.restaurant_id),
        restaurant_name=restaurant_name,
        campaign=promotions.title(promo),
        code=promo.code,
        budget=to_major(promo.budget_cap) if promo.budget_cap is not None else None,
        spent=to_major(spent),
        impressions=promo.impressions,
        clicks=promo.clicks,
        redemptions=redemptions,
        revenue=to_major(revenue),
        status=promotions.state(promo),
        valid_from=promo.valid_from,
        valid_until=promo.valid_until,
        created_at=promo.created_at,
    )


def _state_filter(status: str) -> ColumnElement[bool]:
    now = datetime.now(UTC)
    return {
        "ENDED": PromoCode.valid_until <= now,
        "PAUSED": (PromoCode.valid_until > now) & PromoCode.is_active.is_(False),
        "SCHEDULED": (PromoCode.valid_until > now)
        & PromoCode.is_active.is_(True)
        & (PromoCode.valid_from > now),
        "ACTIVE": (PromoCode.valid_until > now)
        & PromoCode.is_active.is_(True)
        & (PromoCode.valid_from <= now),
    }[status]


async def list_campaigns(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    q: str | None = None,
    restaurant_id: str | None = None,
) -> tuple[list[AdCampaignOut], int, int]:
    """(page, total, active). Newest first."""
    conditions: list[ColumnElement[bool]] = [PromoCode.restaurant_id.is_not(None)]
    if status:
        wanted = status.strip().upper()
        if wanted not in STATUSES:
            raise ValidationError(f"status must be one of: {', '.join(STATUSES)}")
        conditions.append(_state_filter(wanted))
    if q and q.strip():
        pattern = like_pattern(q.strip())
        conditions.append(or_(Restaurant.name.ilike(pattern), PromoCode.code.ilike(pattern)))
    if (rid := parse_uuid(restaurant_id, "restaurant_id")) is not None:
        conditions.append(PromoCode.restaurant_id == rid)

    base = (
        select(PromoCode, Restaurant.name)
        .join(Restaurant, Restaurant.id == PromoCode.restaurant_id)
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    active = await db.scalar(
        select(func.count())
        .select_from(PromoCode)
        .where(PromoCode.restaurant_id.is_not(None), _state_filter("ACTIVE"))
    )
    rows = (
        await db.execute(base.order_by(PromoCode.created_at.desc()).limit(limit).offset(offset))
    ).all()
    figures = await promotions.stats(db, [p.id for p, _ in rows])
    return (
        [_to_out(p, name, figures.get(p.id, (0, 0, 0))) for p, name in rows],
        int(total or 0),
        int(active or 0),
    )


async def set_status(
    db: AsyncSession, admin: User, promo_id: uuid.UUID, status: str
) -> AdCampaignOut:
    """Pause or resume, or end now (final — an ended campaign stays ended)."""
    promo = await db.get(PromoCode, promo_id, with_for_update=True)
    if promo is None or promo.restaurant_id is None:
        raise NotFoundError("Campaign not found")
    now = datetime.now(UTC)
    if promo.valid_until <= now:
        raise ValidationError("This campaign has ended and can no longer be changed")
    if status == "ENDED":
        promo.valid_until = now
    else:
        promo.is_active = status == "ACTIVE"
    await db.flush()
    log.info("ad_campaign_status", promo_id=str(promo.id), status=status, admin_id=str(admin.id))
    restaurant = await db.get(Restaurant, promo.restaurant_id)
    figures = await promotions.stats(db, [promo.id])
    return _to_out(promo, restaurant.name if restaurant else "", figures.get(promo.id, (0, 0, 0)))


async def record_events(db: AsyncSession, body: PromotionEventsRequest) -> dict[str, int]:
    """Bump the counters of every live promotion of each restaurant shown or
    tapped. Duplicates in one batch count once: a card re-rendered by a scroll
    is not a second impression."""
    now = datetime.now(UTC)
    live = (
        PromoCode.is_active.is_(True),
        PromoCode.valid_from <= now,
        PromoCode.valid_until > now,
    )
    counted = {"impressions": 0, "clicks": 0}
    for field, ids in (("impressions", body.impressions), ("clicks", body.clicks)):
        if not ids:
            continue
        column = getattr(PromoCode, field)
        result = await db.execute(
            update(PromoCode)
            .where(PromoCode.restaurant_id.in_(set(ids)), *live)
            .values({field: column + 1})
        )
        counted[field] = int(getattr(result, "rowcount", 0) or 0)
    return counted
