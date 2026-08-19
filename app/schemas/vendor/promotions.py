"""Promotions — offers, budgets, and their live stats."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PromotionDay(BaseModel):
    date: date
    redemptions: int


class PromotionOut(BaseModel):
    """One promotion, list row and detail alike.

    `discount_value` is percent for PERCENTAGE, whole taka for FLAT, absent
    for FREE_DELIVERY. `state` folds the timestamps and flags into the one
    word the card shows: SCHEDULED, ACTIVE, PAUSED or ENDED.
    """

    id: str
    restaurant_id: str
    code: str = Field(description="Auto-generated; customers can also type it at checkout")
    title: str = Field(description='Display label, e.g. "20% OFF" or "Free delivery"')
    discount_type: str
    discount_value: Decimal | None = None
    max_discount: Decimal | None = None
    min_order_amount: Decimal
    applies_to_all_items: bool
    item_ids: list[str] = Field(default_factory=list)
    starts_at: datetime
    ends_at: datetime
    budget_cap: Decimal | None = None
    budget_spent: Decimal
    redemptions: int
    revenue_generated: Decimal = Field(
        description="grand_total of orders that redeemed this offer"
    )
    state: str
    is_active: bool
    created_at: datetime


class PromotionDetail(PromotionOut):
    last_7_days: list[PromotionDay] = Field(default_factory=list)
