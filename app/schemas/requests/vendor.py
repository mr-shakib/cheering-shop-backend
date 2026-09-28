"""Vendor storefront, registration fast path, order actions, business hours."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class SetCommissionRequest(BaseModel):
    """PATCH /admin/restaurants/{id}/commission — [EXTENDED].

    A **fraction**, the same unit `GET /vendor/profile` reads back, not a
    percentage: 0.15 is 15%. Sending 15 is rejected rather than quietly
    charging a vendor 1500% — the ceiling is 1.
    """

    model_config = ConfigDict(extra="forbid")

    commission_rate: Decimal = Field(
        ge=0,
        le=1,
        decimal_places=4,
        description="Platform cut as a fraction of item_total: 0.15 == 15%. "
        "Four decimal places, matching the column.",
    )
    note: str | None = Field(
        default=None, max_length=500, description="Why the rate changed; recorded in the log"
    )


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


# ---------------------------------------------------------------------------
# Admin: add and edit any vendor
# ---------------------------------------------------------------------------

# The document slots on the partner form (ApplicationDocuments' fields).
VendorDocumentKind = Literal["shop_image", "owner_nid", "menu_list", "trade_license"]
_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class AdminVendorPayout(BaseModel):
    """Bank or mobile-wallet details, as on the partner form."""

    method: Literal["BANK", "BKASH", "NAGAD", "ROCKET"]
    account_name: str = Field(min_length=2, max_length=150)
    account_number: str = Field(min_length=4, max_length=50)
    bank_name: str | None = Field(default=None, max_length=150)
    branch_name: str | None = Field(default=None, max_length=150)


class AdminVendorCreateRequest(BaseModel):
    """POST /admin/vendors — [EXTENDED].

    An administrator adding a vendor IS the review, so the store is approved
    (`is_verified`) at creation and customers can find it straight away. It
    starts CLOSED unless `status` says otherwise, like an approved application.

    `owner_password` is optional: without one the owner is emailed the same
    "set your password" instructions an approved applicant gets. Files are
    uploaded first with `POST /admin/uploads/presigned-url`.
    """

    model_config = ConfigDict(extra="forbid")

    # Store
    name: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    phone: str | None = Field(
        default=None, max_length=20, description="Store phone; defaults to the owner's"
    )
    address_line: str = Field(min_length=5, max_length=500)
    area: str | None = Field(default=None, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    cuisine_types: list[str] = Field(default_factory=list, max_length=10)
    logo_url: str | None = Field(default=None, max_length=2048)
    cover_image_url: str | None = Field(default=None, max_length=2048)
    min_order_amount: Money | None = None
    avg_prep_time_mins: int | None = Field(default=None, ge=1, le=240)
    status: Literal["OPEN", "CLOSED"] = "CLOSED"
    is_verified: bool = Field(default=True, description="False adds it unapproved (hidden)")

    # Business
    business_type: Literal["RESTAURANT", "GROCERY", "PHARMACY"] = "RESTAURANT"
    business_category: str = Field(default="General", min_length=2, max_length=80)
    branch_count: int = Field(default=1, ge=1, le=50)
    commission_rate: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
        decimal_places=4,
        description="0.15 == 15%. Omit for the Settings screen's rate for the business type",
    )

    # Owner — the account the vendor app signs in with
    owner_full_name: str = Field(min_length=2, max_length=150)
    owner_email: str = Field(max_length=254, pattern=_EMAIL)
    owner_phone: str = Field(min_length=6, max_length=20)
    owner_password: str | None = Field(default=None, min_length=8, max_length=128)
    national_id: str | None = Field(default=None, min_length=4, max_length=50)

    documents: dict[VendorDocumentKind, str] = Field(
        default_factory=dict, description="Document kind -> URL"
    )
    payout: AdminVendorPayout | None = None


class AdminVendorUpdateRequest(BaseModel):
    """PATCH /admin/vendors/{id} — [EXTENDED]. Every field on Vendor Details.

    PATCH: omitted fields are left alone. `documents` is merged — send a kind
    with a URL to set it, or with null to remove it. Coordinates move
    together. Business fields (type, category, NID, documents, payout) live on
    the vendor's partner record; a vendor registered without one gets one.
    """

    model_config = ConfigDict(extra="forbid")

    # Store
    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    phone: str | None = Field(default=None, max_length=20)
    address_line: str | None = Field(default=None, min_length=5, max_length=500)
    area: str | None = Field(default=None, max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    cuisine_types: list[str] | None = Field(default=None, max_length=10)
    logo_url: str | None = Field(default=None, max_length=2048)
    cover_image_url: str | None = Field(default=None, max_length=2048)
    min_order_amount: Money | None = None
    avg_prep_time_mins: int | None = Field(default=None, ge=1, le=240)
    business_hours: BusinessHoursRequest | None = None
    status: Literal["OPEN", "CLOSED"] | None = None
    is_verified: bool | None = Field(
        default=None, description="Approve (true) or suspend (false); suspending closes the store"
    )
    is_active: bool | None = Field(
        default=None, description="False takes the storefront out of discovery"
    )
    commission_rate: Decimal | None = Field(default=None, ge=0, le=1, decimal_places=4)

    # Business
    business_type: Literal["RESTAURANT", "GROCERY", "PHARMACY"] | None = None
    business_category: str | None = Field(default=None, min_length=2, max_length=80)
    branch_count: int | None = Field(default=None, ge=1, le=50)
    national_id: str | None = Field(default=None, min_length=4, max_length=50)
    documents: dict[VendorDocumentKind, str | None] | None = None
    payout: AdminVendorPayout | None = None

    # Owner
    owner_full_name: str | None = Field(default=None, min_length=2, max_length=150)
    owner_email: str | None = Field(default=None, max_length=254, pattern=_EMAIL)
    owner_phone: str | None = Field(default=None, min_length=6, max_length=20)
    owner_password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description="Issue or reset the owner's password",
    )

    @model_validator(mode="after")
    def _needs_a_field(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        return self
