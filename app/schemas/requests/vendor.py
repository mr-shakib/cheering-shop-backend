"""Vendor storefront, registration fast path, order actions, business hours."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.requests.base import Money, _IdentifierBody


class StoreStatusRequest(BaseModel):
    """PATCH /vendor/store/status"""

    status: Literal["OPEN", "CLOSED"]


class HandoffRequest(BaseModel):
    """POST /vendor/orders/{id}/handoff"""

    rider_pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


class OrderRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class RestaurantProfileUpdateRequest(BaseModel):
    """PATCH /vendor/profile — [EXTENDED].

    Registration was previously the only write to a storefront, so a vendor
    could never add a logo, set a delivery fee, or fix a typo in their address.

    Deliberately absent: `is_verified`, `is_active`, `commission_rate`, `slug`,
    `rating_avg`. The first three are the platform's levers over the vendor and
    cannot be self-served; `slug` is frozen so existing links keep resolving
    after a rename; ratings are derived from reviews and are not an opinion the
    vendor gets to hold. `extra="forbid"` means an attempt to set one is a 400,
    not a silent no-op that looks like it worked.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    phone: str | None = Field(default=None, max_length=20)
    logo_url: str | None = Field(default=None, max_length=2048)
    cover_image_url: str | None = Field(default=None, max_length=2048)
    cuisine_types: list[str] | None = Field(default=None, max_length=10)
    address_line: str | None = Field(default=None, min_length=5, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    delivery_fee_base: Money | None = None
    min_order_amount: Money | None = None
    avg_prep_time_mins: int | None = Field(
        default=None, ge=1, le=240, description="Drives the delivery estimate shown to customers"
    )


class RestaurantDetails(BaseModel):
    """The storefront created alongside a vendor account."""

    name: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    phone: str | None = Field(default=None, max_length=20)
    address_line: str = Field(min_length=5, max_length=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    cuisine_types: list[str] = Field(default_factory=list, max_length=10)


class VendorRegisterRequest(_IdentifierBody):
    """POST /auth/register/vendor — [EXTENDED].

    One call: redeem the OTP, create the VENDOR account, and create its
    restaurant. Splitting these would leave a vendor account with no storefront
    if the second call failed, which nothing else in the system can repair.
    """

    code: str = Field(min_length=4, max_length=8)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=150, description="Owner's name")
    restaurant: RestaurantDetails


class VerifyRestaurantRequest(BaseModel):
    """POST /admin/restaurants/{id}/verify — [EXTENDED]."""

    is_verified: bool = Field(description="True to approve, false to suspend")
    note: str | None = Field(default=None, max_length=500)


class DayHours(BaseModel):
    """One row of the Business Hour screen."""

    is_open: bool
    opens_at: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description='24h "HH:MM"'
    )
    closes_at: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description='24h "HH:MM"'
    )


class BusinessHoursRequest(BaseModel):
    """PUT /vendor/hours — all seven days at once.

    PUT, not PATCH: the screen always shows and saves the whole week, and a
    partial write could leave Tuesday claiming hours from two edits ago.
    A day with `is_open: true` must carry both times; `closes_at` earlier than
    `opens_at` means the store runs past midnight and is allowed.
    """

    mon: DayHours
    tue: DayHours
    wed: DayHours
    thu: DayHours
    fri: DayHours
    sat: DayHours
    sun: DayHours
