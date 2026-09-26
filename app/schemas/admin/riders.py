"""The admin rider screens: roster, profile, earnings, withdrawals, live map,
and the application queue."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.rider import RiderEarnings, RiderEarningsDay, RiderOut, RiderPayoutOut


class AdminRiderRow(RiderOut):
    """One row of Active Rider."""

    avatar_url: str | None = None
    rating_avg: float
    rating_count: int
    live_status: str = Field(description="ONLINE or OFFLINE — on shift or not")


class AdminRiderDetail(AdminRiderRow):
    """Rider Details → Personal Info, plus the header and earnings tiles."""

    date_of_birth: date | None = None
    national_id: str | None = None
    documents: dict[str, str] = Field(default_factory=dict, description="Kind -> URL")
    payout: dict = Field(default_factory=dict, description="Default payout account")
    delivered_orders: int
    cancelled_orders: int = Field(description="Orders cancelled while assigned to this rider")
    earnings: RiderEarnings


class AdminRiderEarnings(BaseModel):
    """Rider Details → Earning: the four tiles and one page of days."""

    summary: RiderEarnings
    days: list[RiderEarningsDay]


class RiderIncentiveOut(BaseModel):
    id: str
    rider_id: str
    amount: Decimal
    reason: str
    created_by: str | None = None
    created_at: datetime


class AdminRiderPayoutRow(RiderPayoutOut):
    """Rider Withdrawal, and Rider Details → Withdrawal."""

    rider_name: str | None = None
    rider_avatar_url: str | None = None
    reopened_at: datetime | None = None
    reopen_reason: str | None = None


class LiveOrderBrief(BaseModel):
    order_id: str
    order_number: int
    status: str
    customer_name: str | None = None
    restaurant_name: str
    distance_to_dropoff_km: float | None = None


class LiveRider(BaseModel):
    """One pin on Live Tracking, and one row of its list."""

    id: str
    full_name: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    vehicle_type: str | None = None
    status: str = Field(
        description="AVAILABLE (no orders), HEADING_TO_PICKUP (assigned, food not "
        "collected) or DELIVERING (carrying food)"
    )
    latitude: float | None = None
    longitude: float | None = None
    location_updated_at: datetime | None = None
    has_live_location: bool = Field(description="False when the rider has not pinged recently")
    orders: list[LiveOrderBrief] = Field(default_factory=list)


class RiderApplicationOut(BaseModel):
    """Rider Application list and Application Details."""

    id: str
    application_no: str = Field(description='e.g. "RDR-48291"')
    full_name: str
    email: str
    phone: str
    vehicle_type: str
    license_number: str | None = None
    date_of_birth: date
    national_id: str
    documents: dict[str, str] = Field(default_factory=dict)
    payout: dict = Field(default_factory=dict)
    status: str = Field(description="PENDING, APPROVED or REJECTED")
    review_note: str | None = None
    reviewed_at: datetime | None = None
    rider_id: str | None = Field(default=None, description="The account approval created")
    submitted_at: datetime


class RiderApplicationSubmitted(BaseModel):
    application_no: str
    status: str
    message: str


class RiderApplicationStatus(BaseModel):
    application_no: str
    status: str
    review_note: str | None = None
    submitted_at: datetime
    reviewed_at: datetime | None = None
