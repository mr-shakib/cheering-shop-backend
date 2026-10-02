"""Customer commerce: cart, checkout, order lifecycle, reviews."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.requests.base import Money


class CartAddOnChoice(BaseModel):
    add_on_id: str
    quantity: int = Field(default=1, ge=1, le=20, description="Per unit of the item")


class CartItemRequest(BaseModel):
    """POST /cart/items.

    A line is one configuration: item + variant + add-ons with their
    quantities. `mode` decides what `quantity` means for that line:

    * `set` (default) — the line's quantity becomes `quantity`; 0 removes it.
    * `add` — `quantity` is added to the line if it already exists (the menu's
      Add to cart), and creates it otherwise.

    Add-ons: send `add_ons` with quantities, or list ids in `add_on_ids` —
    repeating an id counts it twice. Both may be sent; they are combined.
    """

    menu_item_id: str
    variant_id: str | None = None
    add_on_ids: list[str] = Field(default_factory=list, max_length=100)
    add_ons: list[CartAddOnChoice] = Field(default_factory=list, max_length=50)
    quantity: int = Field(ge=0, le=99)
    mode: Literal["set", "add"] = "set"
    notes: str | None = Field(default=None, max_length=255)


class CartLineUpdateRequest(BaseModel):
    """PATCH /cart/items/{line_id} — the cart screen's − and +. 0 removes."""

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
    # The Delivery tab. PRIORITY adds the priority fee and cannot be combined
    # with scheduled_for: a booked slot has a fixed time to be fast towards.
    delivery_type: Literal["STANDARD", "PRIORITY"] = "STANDARD"


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
