"""[EXTENDED] The rider: the roster an administrator maintains, and the job
screens the rider app itself renders.

The specification models a RIDER role but never a rider, so there is no
specified shape for one. These are the fields dispatch and the admin console
actually need: who they are, whether they are on shift, and how much they are
already carrying.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class RiderOut(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool
    vehicle_type: str | None = None
    license_number: str | None = None
    is_online: bool = Field(description="On shift — only online riders are auto-assigned")
    is_verified: bool = Field(description="Cleared to carry orders")
    orders_in_flight: int = Field(
        description="Orders this rider is holding right now — what dispatch balances on"
    )
    total_deliveries: int
    created_at: datetime


class RiderAssignment(BaseModel):
    """POST /admin/orders/{id}/assign-rider"""

    order_id: str
    status: str
    rider: RiderOut
    chosen_by: str = Field(description='"dispatch" when picked automatically, else "operator"')
    message: str


class RiderJobSummary(BaseModel):
    """One row of the rider's job list — enough to render the card."""

    order_id: str
    order_number: int
    status: str
    restaurant_name: str
    restaurant_address: str
    restaurant_latitude: float
    restaurant_longitude: float
    delivery_address_text: str
    delivery_latitude: float
    delivery_longitude: float
    item_count: int
    grand_total: Decimal
    payment_method: str
    collect_on_delivery: Decimal = Field(
        description="Cash to take at the door — grand_total for COD, zero otherwise"
    )
    placed_at: datetime
    ready_at: datetime | None = None
    picked_up_at: datetime | None = None
    delivered_at: datetime | None = None


class RiderJobDetail(RiderJobSummary):
    """The job screen: what to collect, from whom, and where it goes."""

    restaurant_phone: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    special_instructions: str | None = None
    handoff_code: str | None = Field(
        default=None,
        description=(
            "The 4-digit code to read out at the counter — present only while "
            "the order is READY, and only to the rider carrying it"
        ),
    )


class DeliveryResult(BaseModel):
    """POST /rider/orders/{id}/deliver"""

    order_id: str
    restaurant_id: str = Field(
        description="Carried so the completion can be announced on the vendor's channel"
    )
    status: str
    delivered_at: datetime
    payment_status: str
    total_deliveries: int = Field(description="This rider's lifetime count, after this one")
    message: str


class ShiftState(BaseModel):
    """PATCH /rider/me/shift"""

    rider_id: str
    is_online: bool
    orders_in_flight: int
    message: str


class RiderPosition(BaseModel):
    """A live position, as read back from Redis."""

    latitude: float
    longitude: float
    heading: int | None = Field(default=None, description="Degrees clockwise from north")
    speed_kph: float | None = None
    updated_at: datetime | None = None


class LocationAccepted(BaseModel):
    """POST /rider/location — what the app learns from reporting a position."""

    recorded_at: datetime
    orders_notified: int = Field(
        description="How many of this rider's customers received the update live"
    )
    trail_written: bool = Field(
        description="Whether this ping also landed in the audit trail — most do not"
    )
    next_ping_seconds: int = Field(description="How long to wait before reporting again")
