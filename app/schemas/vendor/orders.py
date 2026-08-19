"""The order queue and lifecycle, as the kitchen sees it."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class VendorOrderItemAddOnOut(BaseModel):
    name: str
    price: Decimal


class VendorOrderItemOut(BaseModel):
    """Every field is the snapshot taken at purchase time, never the live menu."""

    id: str
    menu_item_id: str | None = None
    item_name: str
    variant_name: str | None = None
    quantity: int
    unit_price: Decimal
    add_ons_total: Decimal
    line_total: Decimal
    notes: str | None = None
    add_ons: list[VendorOrderItemAddOnOut] = Field(default_factory=list)


class VendorOrderSummary(BaseModel):
    """One row of the queue. Deliberately does NOT carry line items — the
    queue is polled and pushed frequently, and the detail view exists for
    the moment a vendor actually starts cooking."""

    id: str
    restaurant_id: str
    order_number: int
    status: str
    payment_method: str
    payment_status: str
    item_count: int
    item_total: Decimal
    grand_total: Decimal
    commission_amount: Decimal
    vendor_payout: Decimal = Field(
        description="item_total - commission_amount, from the per-order "
        "snapshot. Changing the commission rate never rewrites this."
    )
    placed_at: datetime
    accepted_at: datetime | None = None
    ready_at: datetime | None = None
    picked_up_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    auto_decline_at: datetime | None = Field(
        default=None, description="When an unaccepted order is declined automatically"
    )
    seconds_to_auto_decline: int | None = Field(
        default=None, description="Countdown for the vendor tablet; null once accepted"
    )


class VendorOrderDetail(VendorOrderSummary):
    """What the kitchen actually needs: the lines, the notes, the address."""

    items: list[VendorOrderItemOut] = Field(default_factory=list)
    customer_name: str | None = None
    customer_phone: str | None = Field(
        default=None,
        description="The order's delivery contact, not the account's number",
    )
    delivery_address_text: str
    special_instructions: str | None = None
    cancellation_reason: str | None = None
    cancelled_by: str | None = None
    rider_pin_issued: bool = Field(
        description="True once the order is READY and a handoff PIN exists"
    )
    handoff_code: str | None = Field(
        default=None,
        description="The 4-digit code the handoff screen shows — present only "
        "while the order is READY, and only to the owning vendor",
    )


class HandoffResult(BaseModel):
    """POST /vendor/orders/{id}/handoff"""

    order_id: str
    status: str
    picked_up_at: datetime
    message: str
