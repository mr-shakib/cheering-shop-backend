"""The admin Orders screen: the platform-wide table and the order drawer."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.vendor import VendorOrderItemOut


class AdminOrderRow(BaseModel):
    """One row of the Orders table, and of every tab that reuses it (a
    customer's, vendor's or rider's order list)."""

    id: str
    order_number: int = Field(description='Render as "ORD-{order_number}"')
    status: str
    payment_method: str
    payment_status: str
    customer_id: str
    customer_name: str | None = None
    restaurant_id: str
    restaurant_name: str
    business_type: str | None = Field(
        default=None,
        description="RESTAURANT, GROCERY or PHARMACY — the Food / Grocery / Medicine "
        "badge. Null for a restaurant created without an application.",
    )
    rider_id: str | None = None
    rider_name: str | None = None
    delivery_type: str = Field(default="STANDARD", description="STANDARD or PRIORITY")
    grand_total: Decimal
    commission_amount: Decimal
    placed_at: datetime
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None


class AdminOrderEvent(BaseModel):
    """One dot on the order timeline, straight from the status history."""

    status: str
    at: datetime
    actor: str = Field(description="CUSTOMER, VENDOR, RIDER, ADMIN or SYSTEM")
    note: str | None = None


class AdminOrderCustomer(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = Field(default=None, description="The account's phone")
    delivery_contact_phone: str | None = Field(
        default=None, description="The number on this order — call this one"
    )
    delivery_address_text: str
    delivery_latitude: float
    delivery_longitude: float


class AdminOrderVendor(BaseModel):
    id: str
    name: str
    phone: str | None = None
    logo_url: str | None = None
    address_line: str | None = None
    business_type: str | None = None


class AdminOrderRider(BaseModel):
    id: str
    full_name: str | None = None
    phone: str | None = None
    vehicle_type: str | None = None
    rating_avg: float | None = None


class AdminRiderLocation(BaseModel):
    """Where the rider is now. Present only while the order is READY or
    PICKED_UP and the rider has pinged recently; a stale dot is never shown."""

    latitude: float
    longitude: float
    updated_at: datetime | None = None
    distance_to_dropoff_km: float


class AdminOrderMoney(BaseModel):
    """The bill as charged. VAT and packaging are no longer charged; they stay
    here because orders placed before that carried them, and the drawer's
    lines must add up to their grand_total. 0 on every new order."""

    item_total: Decimal
    delivery_fee: Decimal
    priority_fee: Decimal = Field(description="Paid to the rider; 0 unless PRIORITY")
    packaging_fee: Decimal
    tax_amount: Decimal
    platform_fee: Decimal
    tip: Decimal
    discount: Decimal
    grand_total: Decimal
    commission_amount: Decimal = Field(description="The platform's cut, snapshotted at placement")
    vendor_payout: Decimal = Field(description="item_total − commission_amount")


class AdminOrderPayment(BaseModel):
    method: str
    status: str
    reference: str | None = None
    refunded_at: datetime | None = None
    refunded_by: str | None = None
    refund_reason: str | None = None


class AdminOrderActions(BaseModel):
    """Which drawer buttons to enable. The server decides so the console
    never offers something the state machine will refuse."""

    can_assign_rider: bool
    can_cancel: bool
    can_refund: bool
    can_force_deliver: bool


class AdminOrderDetail(AdminOrderRow):
    """The order drawer."""

    timeline: list[AdminOrderEvent]
    customer: AdminOrderCustomer
    vendor: AdminOrderVendor
    rider: AdminOrderRider | None = None
    rider_location: AdminRiderLocation | None = None
    money: AdminOrderMoney
    payment: AdminOrderPayment
    items: list[VendorOrderItemOut]
    special_instructions: str | None = None
    scheduled_for: datetime | None = None
    estimated_delivery_at: datetime | None = None
    cancelled_by: str | None = None
    cancellation_reason: str | None = None
    actions: AdminOrderActions
