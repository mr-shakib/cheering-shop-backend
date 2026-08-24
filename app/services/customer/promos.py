"""Promo code validation — shared by the checkout quote and order placement.

Split out because both callers must apply *identical* rules. A code that
discounts ৳50 on the summary screen and ৳0 at placement is worse than one that
never worked: the customer agreed to a number that then changed.

`validate` never raises for a bad code. Checkout must still return a bill when
a promo is rejected — with the reason attached, so the client can say "this
code expired" rather than silently dropping it and leaving the customer to
wonder why the total did not move.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import percentage_of
from app.models.promo import PromoCode, PromoRedemption


@dataclass(frozen=True)
class PromoResult:
    """`code` is None when nothing was applied; `error` says why."""

    discount: int = 0
    promo: PromoCode | None = None
    error: str | None = None

    @property
    def code(self) -> str | None:
        return self.promo.code if self.promo else None


async def validate(
    db: AsyncSession,
    raw_code: str | None,
    *,
    user_id: uuid.UUID,
    restaurant_id: uuid.UUID,
    item_total: int,
) -> PromoResult:
    """Resolve a code to a discount in paisa, or an explained refusal."""
    if not raw_code or not raw_code.strip():
        return PromoResult()
    code = raw_code.strip()

    # `promo_codes.code` is CITEXT, so this comparison is case-insensitive
    # without a lower() that would defeat the unique index.
    promo = await db.scalar(select(PromoCode).where(PromoCode.code == code))
    if promo is None:
        return PromoResult(error="That promo code does not exist")
    if not promo.is_active:
        return PromoResult(error="That promo code is no longer active")

    # Database clock, not the app's: valid_from/valid_until are timestamptz
    # and comparing them against a worker's clock invites skew. The fallback
    # only exists to satisfy the Optional return type.
    now = await db.scalar(select(func.now())) or datetime.now(UTC)
    if promo.valid_from > now:
        return PromoResult(error="That promo code is not active yet")
    if promo.valid_until < now:
        return PromoResult(error="That promo code has expired")

    # A restaurant-scoped code is scoped; a NULL restaurant_id is platform-wide.
    if promo.restaurant_id is not None and promo.restaurant_id != restaurant_id:
        return PromoResult(error="That promo code is not valid at this restaurant")
    if item_total < promo.min_order_amount:
        from app.core.money import to_major

        return PromoResult(
            error=f"Spend at least {to_major(promo.min_order_amount)} taka to use this code"
        )
    if promo.usage_limit is not None and promo.times_used >= promo.usage_limit:
        return PromoResult(error="That promo code has been fully claimed")

    used_by_user = await db.scalar(
        select(func.count())
        .select_from(PromoRedemption)
        .where(PromoRedemption.promo_code_id == promo.id, PromoRedemption.user_id == user_id)
    )
    if used_by_user and used_by_user >= promo.per_user_limit:
        return PromoResult(error="You have already used this promo code")

    if str(promo.discount_type) == "PERCENTAGE":
        # Stored in basis points (see the vendor promotions module).
        discount = percentage_of(item_total, promo.discount_value)
        if promo.max_discount is not None:
            discount = min(discount, promo.max_discount)
    else:
        discount = promo.discount_value

    # The budget cap is enforced here as a hard stop rather than a partial
    # discount: half a promo is not what was advertised.
    if promo.budget_cap is not None:
        spent = await db.scalar(
            select(func.coalesce(func.sum(PromoRedemption.discount_applied), 0)).where(
                PromoRedemption.promo_code_id == promo.id
            )
        )
        if int(spent or 0) + discount > promo.budget_cap:
            return PromoResult(error="That promo code has reached its budget")

    return PromoResult(discount=min(discount, item_total), promo=promo)


__all__ = ["PromoResult", "validate"]
