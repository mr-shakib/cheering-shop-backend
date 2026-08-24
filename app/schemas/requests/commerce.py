"""Customer commerce: cart, checkout, order lifecycle, reviews."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.requests.base import Money


class CartItemRequest(BaseModel):
    """POST /cart/items — quantity 0 removes the line."""

    menu_item_id: str
    variant_id: str | None = None
    add_on_ids: list[str] = Field(default_factory=list)
    quantity: int = Field(ge=0, le=99)
    notes: str | None = Field(default=None, max_length=255)


class OrderCreateRequest(BaseModel):
    """POST /orders"""

    payment_method: Literal["COD", "WALLET", "BKASH", "CARD"]
    address_id: str
    promo_code: str | None = None
    tip: Money = Decimal(0)
    special_instructions: str | None = Field(default=None, max_length=500)
    # Scheduled delivery. Omit for "as soon as possible". Re-validated against
    # the same lead time the slot generator uses — a client can post any
    # timestamp regardless of which slots were offered.
    scheduled_for: datetime | None = Field(
        default=None, description="Slot start from GET /restaurants/{id}/schedule"
    )


class OrderCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class ChatMessageRequest(BaseModel):
    """POST /orders/{id}/messages — the Message screen's composer."""

    body: str = Field(min_length=1, max_length=2000)


class ReviewCreateRequest(BaseModel):
    """POST /orders/{id}/reviews"""

    restaurant_rating: int = Field(ge=1, le=5)
    rider_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
