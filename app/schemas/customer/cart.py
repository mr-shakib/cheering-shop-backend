"""Cart and the checkout bill — spec #26–28."""

from decimal import Decimal

from pydantic import BaseModel, Field


class CartLineOut(BaseModel):
    """One line. Prices are LIVE, never a snapshot.

    The cart stores quantity and configuration, not money. A vendor who
    re-prices a dish must not have an old price honoured because something sat
    in a cart overnight — and the customer sees the change before committing,
    which is the point of recomputing here rather than at order time.
    """

    id: str
    menu_item_id: str
    name: str
    image_url: str | None = None
    quantity: int
    variant_id: str | None = None
    variant_name: str | None = None
    add_on_ids: list[str] = Field(default_factory=list)
    add_on_names: list[str] = Field(default_factory=list)
    unit_price: Decimal
    add_ons_total: Decimal = Field(description="Per single unit, not multiplied")
    line_total: Decimal
    notes: str | None = None
    # False when the vendor turned the dish off after it was added. The Cart
    # screen greys the row and checkout refuses until it is removed.
    is_available: bool = True


class CartOut(BaseModel):
    """Spec #26. `restaurant_id` is null only for an empty cart.

    One restaurant per cart, enforced by paired composite foreign keys in the
    database — the API check exists to return a courteous 409 rather than let
    the constraint surface as a 500.
    """

    id: str | None = None
    restaurant_id: str | None = None
    restaurant_name: str | None = None
    restaurant_is_open: bool = True
    items: list[CartLineOut] = Field(default_factory=list)
    item_total: Decimal = Decimal(0)
    item_count: int = 0
    min_order_amount: Decimal = Decimal(0)
    # Surfaced so the Cart screen can disable Checkout with a reason rather
    # than letting the customer discover it at the summary call.
    meets_minimum: bool = True


class CheckoutSummary(BaseModel):
    """Spec #28. The backend is the single source of truth for pricing.

    Every field is whole taka. The same arithmetic is re-run and persisted by
    POST /orders, where a CHECK constraint refuses a total that does not add
    up — see services/pricing.py.
    """

    item_total: Decimal
    delivery_fee: Decimal
    packaging_fee: Decimal
    tax_amount: Decimal
    platform_fee: Decimal
    discount: Decimal
    tip: Decimal
    grand_total: Decimal
    distance_km: float
    estimated_delivery_minutes: int
    promo_code: str | None = None
    # Populated when a code was sent but not applied. Silently dropping an
    # invalid promo is how support tickets are made.
    promo_error: str | None = None
