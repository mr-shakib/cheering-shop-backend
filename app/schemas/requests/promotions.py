"""Promotions — launching and controlling offers."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PromotionCreateRequest(BaseModel):
    """POST /vendor/promotions — the New Promotion form."""

    discount_type: Literal["PERCENTAGE", "FLAT", "FREE_DELIVERY"] = Field(
        description="Percentage / Flat amount / Free delivery"
    )
    discount_value: Decimal | None = Field(
        default=None,
        gt=0,
        description="Percent (1–100) for PERCENTAGE, whole taka for FLAT. "
        "Omit for FREE_DELIVERY.",
    )
    max_discount: Decimal | None = Field(
        default=None, gt=0, description="PERCENTAGE only: cap per order, whole taka"
    )
    min_order_amount: Decimal = Field(default=Decimal(0), ge=0, description="Whole taka")
    item_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=200,
        description="Menu items the offer applies to; omit or null for the whole menu",
    )
    starts_at: datetime | None = Field(default=None, description="Defaults to now")
    ends_at: datetime
    budget_cap: Decimal | None = Field(
        default=None,
        gt=0,
        description="Whole taka. Redemption stops once total discount spend reaches this.",
    )


class PromotionUpdateRequest(BaseModel):
    """PATCH /vendor/promotions/{id} — Pause / resume / end early.

    `end_now: true` is irreversible; `is_active` toggles pause. Everything
    else about a live promotion is frozen — changing the discount under
    customers who have already seen the offer is a bait-and-switch.
    """

    is_active: bool | None = None
    end_now: bool | None = None
