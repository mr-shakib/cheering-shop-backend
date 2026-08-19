"""Storefront: the owner's profile view, the OPEN/CLOSED toggle, business hours."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class RestaurantProfile(BaseModel):
    """The vendor's full view of their own storefront.

    Distinct from `RestaurantSummary` (which registration returns) and from the
    public restaurant payload: it exposes settings only the owner may see, and
    it is readable while `is_verified` is still false — discovery is not.
    """

    id: str
    owner_id: str
    name: str
    slug: str = Field(description="Frozen at registration; renaming does not change it")
    description: str | None = None
    cuisine_types: list[str] = Field(default_factory=list)
    phone: str | None = None
    logo_url: str | None = None
    cover_image_url: str | None = None

    status: str = Field(description="OPEN or CLOSED — the vendor's own toggle")
    is_verified: bool = Field(description="Set by an administrator, not by the vendor")
    is_active: bool
    is_accepting_orders: bool = Field(
        description="Derived: true only when active, verified and OPEN. This is "
        "the flag that decides whether customers can order."
    )

    rating_avg: float
    rating_count: int

    address_line: str | None = None
    latitude: float
    longitude: float

    delivery_fee_base: Decimal
    min_order_amount: Decimal
    avg_prep_time_mins: int
    commission_rate: Decimal = Field(
        description="Platform commission as a fraction (0.15 == 15%). Read-only "
        "to the vendor; only an administrator can change it."
    )

    created_at: datetime
    updated_at: datetime


class StoreStatusResult(BaseModel):
    """PATCH /vendor/store/status"""

    restaurant_id: str
    status: str
    is_accepting_orders: bool
    message: str


class DayHoursOut(BaseModel):
    is_open: bool
    opens_at: str | None = None
    closes_at: str | None = None


class BusinessHoursOut(BaseModel):
    """GET/PUT /vendor/hours.

    Informational: customers see these, but nothing opens or closes the store
    automatically — `store_status` remains the only real switch, which is why
    it is echoed here.
    """

    restaurant_id: str
    is_configured: bool = Field(description="False until the vendor first saves hours")
    days: dict[str, DayHoursOut] = Field(description="mon..sun, always all seven")
    store_status: str
