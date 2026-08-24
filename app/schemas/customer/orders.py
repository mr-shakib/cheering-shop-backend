"""Orders, tracking and reviews — spec #29–33."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class OrderItemOut(BaseModel):
    """A line as it was bought. Names and prices are SNAPSHOTS.

    A dish renamed or re-priced next week must not rewrite what this receipt
    says was ordered — which is why order_items carries its own name column
    rather than joining to menu_items at read time.
    """

    id: str
    menu_item_id: str | None = None
    name: str
    quantity: int
    unit_price: Decimal
    add_ons_total: Decimal
    line_total: Decimal
    variant_name: str | None = None
    add_on_names: list[str] = Field(default_factory=list)
    image_url: str | None = None
    notes: str | None = None


class OrderStatusEvent(BaseModel):
    """One dot on the Ride Assign / Track Order timeline."""

    status: str
    at: datetime
    note: str | None = None


class OrderSummary(BaseModel):
    """A row in Order history. Enough to render the card, nothing more."""

    id: str
    order_number: int
    status: str
    restaurant_id: str
    restaurant_name: str
    restaurant_logo_url: str | None = None
    item_count: int
    grand_total: Decimal
    payment_method: str
    payment_status: str
    placed_at: datetime
    delivered_at: datetime | None = None
    scheduled_for: datetime | None = None
    # Drives the "Rate this order" affordance without a second request.
    can_review: bool = False
    can_cancel: bool = False


class OrderDetail(OrderSummary):
    """The Order Details screen — the full receipt plus the timeline."""

    items: list[OrderItemOut] = Field(default_factory=list)
    item_total: Decimal
    delivery_fee: Decimal
    packaging_fee: Decimal
    tax_amount: Decimal
    platform_fee: Decimal
    discount: Decimal
    tip: Decimal
    delivery_address_text: str
    delivery_latitude: float
    delivery_longitude: float
    delivery_contact_phone: str | None = None
    special_instructions: str | None = None
    estimated_delivery_at: datetime | None = None
    cancellation_reason: str | None = None
    timeline: list[OrderStatusEvent] = Field(default_factory=list)
    rider: "RiderBrief | None" = None


class RiderBrief(BaseModel):
    """What the customer may see about their rider.

    Name, photo, rating and a masked-call handle — never the real phone number.
    `POST /orders/{id}/call` bridges the two parties without either learning
    the other's number.
    """

    id: str
    full_name: str
    avatar_url: str | None = None
    rating_avg: float | None = None
    vehicle_type: str | None = None


class OrderTracking(BaseModel):
    """Spec #31. Initialises the map, then the WebSocket streams updates.

    `rider_location` is null until a rider app exists to report one. It is
    deliberately absent rather than simulated: a moving dot that does not
    correspond to a real courier is worse than no dot.
    """

    order_id: str
    status: str
    timeline: list[OrderStatusEvent] = Field(default_factory=list)
    restaurant_latitude: float
    restaurant_longitude: float
    restaurant_name: str
    delivery_latitude: float
    delivery_longitude: float
    delivery_address_text: str
    estimated_delivery_at: datetime | None = None
    eta_minutes: int | None = None
    rider: RiderBrief | None = None
    rider_location: dict | None = None
    live_tracking_available: bool = False


class ReviewOut(BaseModel):
    id: str
    order_id: str
    restaurant_rating: int
    rider_rating: int | None = None
    comment: str | None = None
    created_at: datetime
    author_name: str | None = None


class PlacedOrder(BaseModel):
    """The POST /orders response — what the Order Complete screen renders."""

    id: str
    order_number: int
    status: str
    grand_total: Decimal
    payment_method: str
    payment_status: str
    estimated_delivery_at: datetime | None = None
    scheduled_for: datetime | None = None
    restaurant_id: str
    restaurant_name: str
    placed_at: datetime


OrderDetail.model_rebuild()
