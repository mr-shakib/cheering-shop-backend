"""Admin console actions: orders, accounts and products."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.requests.vendor_menu import MenuItemCreateRequest, MenuItemUpdateRequest


class AdminOrderCancelRequest(BaseModel):
    """POST /admin/orders/{id}/cancel — the reason is shown to the customer
    and the vendor, and recorded in the status history."""

    reason: str = Field(min_length=3, max_length=255)


class AdminOrderRefundRequest(BaseModel):
    """POST /admin/orders/{id}/refund — recorded on the order as the refund
    reason, so write it for whoever reads the dispute later."""

    reason: str = Field(min_length=3, max_length=255)


class UserStatusRequest(BaseModel):
    """PATCH /admin/users/{id}/status — block or unblock an account."""

    is_active: bool = Field(description="false blocks the account and signs it out everywhere")


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

CommissionRate = Annotated[
    Decimal,
    Field(ge=0, le=1, description="A fraction: 0.15 is 15%. Sending 15 is rejected."),
]

_ADMIN_PRODUCT_FIELDS = """
Admin-only fields, on top of everything the vendor can edit:

* `commission_rate` — this product's own rate. `null` clears it, and the
  category's (then the restaurant's) rate applies again.
* `is_hidden` — off every customer screen; the vendor cannot undo it.
* `is_featured` — the Featured button.
* `platform_category_id` — move the product under another browse category.
  It moves into the restaurant's menu section for that category, which is
  created (named after the category) if the restaurant has none.
"""


class AdminProductUpdateRequest(MenuItemUpdateRequest):
    __doc__ = "PATCH /admin/products/{id} — PATCH semantics.\n" + _ADMIN_PRODUCT_FIELDS

    commission_rate: CommissionRate | None = None
    is_hidden: bool | None = None
    is_featured: bool | None = None
    platform_category_id: str | None = None

    @model_validator(mode="after")
    def _one_way_to_move(self) -> "AdminProductUpdateRequest":
        if self.category_id is not None and self.platform_category_id is not None:
            raise ValueError("Send category_id or platform_category_id, not both")
        return self


class AdminProductCreateRequest(MenuItemCreateRequest):
    __doc__ = (
        "POST /admin/vendors/{id}/products — Add Product on a vendor's behalf.\n\n"
        "Name the menu section with `category_id`, or the browse category with "
        "`platform_category_id`; exactly one.\n" + _ADMIN_PRODUCT_FIELDS
    )

    model_config = ConfigDict(extra="forbid")

    category_id: str | None = None  # type: ignore[assignment]
    platform_category_id: str | None = None
    commission_rate: CommissionRate | None = None
    is_featured: bool = False

    @model_validator(mode="after")
    def _exactly_one_home(self) -> "AdminProductCreateRequest":
        if (self.category_id is None) == (self.platform_category_id is None):
            raise ValueError("Send exactly one of category_id or platform_category_id")
        return self


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

TakaAmount = Annotated[Decimal, Field(ge=0, le=100_000, description="Whole taka")]


class SurchargeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: TakaAmount | None = None
    active: bool | None = None


class PlatformSettingsUpdateRequest(BaseModel):
    """PATCH /admin/settings — omitted fields are left alone. An explicit
    `null` on any field except the surcharges hands it back to the server
    default. Commission rates are fractions (0.18 == 18%)."""

    model_config = ConfigDict(extra="forbid")

    app_name: str | None = Field(default=None, min_length=1, max_length=80)
    support_email: str | None = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    support_phone: str | None = Field(default=None, min_length=6, max_length=20)
    delivery_base_fee: TakaAmount | None = None
    delivery_per_km_fee: TakaAmount | None = None
    delivery_min_fee: TakaAmount | None = None
    restaurant_commission_rate: CommissionRate | None = None
    grocery_commission_rate: CommissionRate | None = None
    pharmacy_commission_rate: CommissionRate | None = None
    rain_surcharge: SurchargeUpdate | None = None
    heatwave_fee: SurchargeUpdate | None = None
    high_demand_fee: SurchargeUpdate | None = None


# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------


class AttachmentIn(BaseModel):
    url: str = Field(max_length=2048, description="From POST /uploads/presigned-url")
    name: str = Field(min_length=1, max_length=200)


class SupportTicketCreateRequest(BaseModel):
    """POST /support/tickets — any signed-in customer, vendor or rider."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=3, max_length=200)
    type: Literal[
        "ORDER_ISSUE",
        "RIDER_COMPLAINT",
        "VENDOR_COMPLAINT",
        "PAYMENT",
        "REFUND",
        "ACCOUNT",
        "OTHER",
    ]
    message: str = Field(min_length=1, max_length=5000)
    order_id: str | None = Field(default=None, description="The order it is about, if any")
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=10)


class SupportMessageRequest(BaseModel):
    """POST …/messages — a reply, from either side."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=5000)
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=10)


class SupportTicketUpdateRequest(BaseModel):
    """PATCH /admin/support/tickets/{id} — the Close button, priority, and
    assignment. `assigned_to: null` unassigns."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["OPEN", "PENDING", "RESOLVED", "CLOSED"] | None = None
    priority: Literal["LOW", "MEDIUM", "HIGH", "URGENT"] | None = None
    assigned_to: uuid.UUID | None = None

    @model_validator(mode="after")
    def _needs_a_field(self) -> "SupportTicketUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Send status, priority or assigned_to")
        return self


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class NotificationCampaignRequest(BaseModel):
    """POST /admin/notifications — omit `scheduled_for` to send now."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    type: Literal["PROMOTION", "ALERT", "UPDATE"] = "PROMOTION"
    audience: Literal["CUSTOMER", "VENDOR", "RIDER", "ALL"]
    scheduled_for: datetime | None = Field(
        default=None, description="Timezone-aware; must be in the future. Omit to send now."
    )


class DeviceRegisterRequest(BaseModel):
    """POST /users/me/devices — call after sign-in and whenever FCM rotates
    the token."""

    fcm_token: str = Field(min_length=10, max_length=4096)
    platform: Literal["IOS", "ANDROID", "WEB"]


# ---------------------------------------------------------------------------
# Administrator invitations
# ---------------------------------------------------------------------------


class AdminInvitationRequest(BaseModel):
    """POST /admin/invitations"""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str | None = Field(default=None, max_length=150)


class AdminInvitationAcceptRequest(BaseModel):
    """POST /auth/admin-invitations/accept — the Sign up for admin form. The
    email comes from the invitation, not the form, so it cannot be changed."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Advertisements
# ---------------------------------------------------------------------------


class AdCampaignUpdateRequest(BaseModel):
    """PATCH /admin/advertisements/{id} — pause, resume, or end for good."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ACTIVE", "PAUSED", "ENDED"]


class PromotionEventsRequest(BaseModel):
    """POST /promotions/events — batched from the app. Ids are the restaurant
    ids of promoted cards (the home feed's `promoted` row) that were shown or
    tapped; each counts toward that restaurant's live promotions."""

    impressions: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    clicks: list[uuid.UUID] = Field(default_factory=list, max_length=50)


# ---------------------------------------------------------------------------
# Community
# ---------------------------------------------------------------------------


class CommunityPostRequest(BaseModel):
    """POST /community/posts — upload images first via /uploads/presigned-url."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)
    image_urls: list[str] = Field(default_factory=list, max_length=4)
    restaurant_id: uuid.UUID | None = Field(default=None, description="Tag a restaurant")


class CommunityReportRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class CommunityRemoveRequest(BaseModel):
    """POST /admin/community/posts/{id}/remove"""

    reason: str = Field(min_length=3, max_length=255)
