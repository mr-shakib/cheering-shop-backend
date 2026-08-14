"""Request bodies the specification documents verbatim (§4).

Only bodies the spec actually spells out are modelled here. The rest arrive with
their modules in Step 4 — inventing them now would be guessing at contracts.
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Money = Annotated[Decimal, Field(ge=0, description="Whole taka; stored as paisa")]


class OtpSendRequest(BaseModel):
    """POST /auth/otp/send"""

    identifier: str = Field(description="Email address or phone number")


class OtpVerifyRequest(BaseModel):
    """POST /auth/otp/verify"""

    identifier: str
    code: str = Field(min_length=4, max_length=8)


class LoginRequest(BaseModel):
    """POST /auth/login"""

    identifier: str
    password: str = Field(min_length=8)


class Login2FARequest(BaseModel):
    """POST /auth/login/2fa"""

    temp_token: str
    code: str = Field(min_length=6, max_length=6)


class PasswordForgotRequest(BaseModel):
    identifier: str


class PasswordResetRequest(BaseModel):
    """POST /auth/password/reset

    The spec shows a bare `token`. We use identifier + the OTP code issued by
    /auth/password/forgot instead: it reuses the same rate-limited, attempt-
    capped, single-use OTP machinery rather than introducing a second
    credential type with its own expiry and revocation rules.
    """

    identifier: str
    code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8)


class RefreshRequest(BaseModel):
    """POST /auth/refresh — [EXTENDED], see the endpoint docstring."""

    refresh_token: str


class TotpEnableRequest(BaseModel):
    """POST /auth/2fa/enable — proves the user can generate a valid code."""

    code: str = Field(min_length=6, max_length=6)


class BiometricsEnableRequest(BaseModel):
    device_id: str
    device_name: str | None = None
    public_key: str = Field(description="Device-bound public key for challenge verification")


class AddressCreateRequest(BaseModel):
    """POST /users/me/addresses"""

    type: Literal["HOME", "WORK", "OTHER"] = "OTHER"
    street_address: str
    apartment: str | None = None
    landmark: str | None = None
    city: str | None = None
    postal_code: str | None = None
    contact_phone: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_default: bool = False


class CartItemRequest(BaseModel):
    """POST /cart/items — quantity 0 removes the line."""

    menu_item_id: str
    variant_id: str | None = None
    add_on_ids: list[str] = Field(default_factory=list)
    quantity: int = Field(ge=0, le=99)
    notes: str | None = Field(default=None, max_length=255)


class OrderCreateRequest(BaseModel):
    """POST /orders"""

    payment_method: Literal["COD", "WALLET", "BKASH", "CARD"]
    address_id: str
    promo_code: str | None = None
    tip: Money = Decimal(0)
    special_instructions: str | None = Field(default=None, max_length=500)


class OrderCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class ReviewCreateRequest(BaseModel):
    """POST /orders/{id}/reviews"""

    restaurant_rating: int = Field(ge=1, le=5)
    rider_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class StoreStatusRequest(BaseModel):
    """PATCH /vendor/store/status"""

    status: Literal["OPEN", "CLOSED"]


class HandoffRequest(BaseModel):
    """POST /vendor/orders/{id}/handoff"""

    rider_pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


class OrderRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class VariantRequest(BaseModel):
    name: str
    price: Money


class AddOnRequest(BaseModel):
    name: str
    price: Money


class MenuItemCreateRequest(BaseModel):
    """POST /vendor/menu/items"""

    name: str
    category_id: str
    description: str | None = None
    base_price: Money
    is_available: bool = True
    is_veg: bool = False
    variants: list[VariantRequest] = Field(default_factory=list)
    add_ons: list[AddOnRequest] = Field(default_factory=list)
    image_url: str | None = None


class MenuItemStatusRequest(BaseModel):
    """PATCH /vendor/menu/items/{id}/status"""

    is_available: bool


class PresignedUrlRequest(BaseModel):
    """POST /uploads/presigned-url"""

    file_type: str = Field(description="MIME type, e.g. image/jpeg")
    file_name: str | None = None
