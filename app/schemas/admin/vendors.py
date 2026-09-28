"""The admin Vendor screens: the active list and the vendor profile tabs."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.vendor import PayoutOut, ReviewsSummary, VendorReviewOut


class AdminVendorRow(BaseModel):
    id: str
    name: str
    logo_url: str | None = None
    business_type: str | None = Field(
        default=None, description="RESTAURANT, GROCERY or PHARMACY; null without an application"
    )
    phone: str | None = None
    order_count: int = Field(description="DELIVERED orders")
    revenue: Decimal = Field(description="Sum of item_total over DELIVERED orders")
    rating_avg: float
    rating_count: int
    product_count: int = Field(description="Menu items not deleted")
    status: str = Field(description="OPEN or CLOSED — the store toggle")
    is_verified: bool
    is_active: bool
    created_at: datetime


class AdminVendorOwner(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    national_id: str | None = Field(default=None, description="From the application")


class AdminVendorDetail(AdminVendorRow):
    """Vendor Details → Store Info, plus the header card."""

    slug: str
    description: str | None = None
    cover_image_url: str | None = None
    cuisine_types: list[str]
    business_category: str | None = None
    address_line: str | None = None
    latitude: float
    longitude: float
    owner: AdminVendorOwner
    business_hours: dict | None = None
    avg_prep_time_mins: int
    min_order_amount: Decimal
    delivery_fee_base: Decimal
    commission_rate: float = Field(description="0.15 == 15%")
    application_id: str | None = None
    application_no: str | None = None
    onboarding_source: str | None = Field(
        default=None,
        description="APPLICATION (partner form), ADMIN (added in the console), "
        "or null (registered through the API fast path, no partner record)",
    )
    area: str | None = None
    documents: dict[str, str] = Field(
        default_factory=dict, description="Document kind -> URL, from the application"
    )
    payout: dict = Field(default_factory=dict, description="Bank / mobile-wallet details")


class AdminVendorReviews(BaseModel):
    """Vendor Details → Review: the rating header and one page of reviews."""

    summary: ReviewsSummary
    reviews: list[VendorReviewOut]


class AdminVendorFinance(BaseModel):
    """Vendor Details → Withdrawal: the four tiles. The settlement table below
    them is `GET /admin/payouts?restaurant_id=`."""

    restaurant_id: str
    total_earning: Decimal = Field(description="Sum of item_total over DELIVERED orders")
    total_commission: Decimal
    total_payout: Decimal = Field(description="COMPLETED payouts")
    pending_amount: Decimal = Field(description="PROCESSING payouts")
    available_balance: Decimal = Field(description="What the vendor could withdraw now")


class AdminPayoutRow(PayoutOut):
    """A payout in the admin queue, with the vendor it belongs to."""

    restaurant_name: str
    reopened_at: datetime | None = Field(
        default=None, description="Set when a COMPLETED payout was taken back (Mark Unpaid)"
    )
    reopen_reason: str | None = None
