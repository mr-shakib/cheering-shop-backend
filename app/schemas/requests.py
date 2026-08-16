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
    """POST /auth/otp/verify

    `password` is optional and is the ONLY point at which a brand-new account
    can acquire one. Without it, `/auth/login` is unreachable for a new user:
    the only other path to `set_password` is `/auth/password/reset`, which
    itself needs an OTP. Supplying it here turns signup into a single round
    trip instead of signup-then-immediately-reset.
    """

    identifier: str
    code: str = Field(min_length=4, max_length=8)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=150)


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
    """POST /auth/biometrics/enable

    `public_key` is base64-encoded DER SubjectPublicKeyInfo. `algorithm` must
    match how the device will sign: iOS Secure Enclave can only do ES256.
    """

    device_id: str = Field(max_length=255)
    device_name: str | None = Field(default=None, max_length=120)
    public_key: str = Field(description="base64 DER SubjectPublicKeyInfo")
    algorithm: Literal["ES256", "ED25519"] = "ES256"


class BiometricChallengeRequest(BaseModel):
    """POST /auth/biometrics/challenge — [EXTENDED]."""

    device_id: str = Field(max_length=255)


class BiometricLoginRequest(BaseModel):
    """POST /auth/biometrics/login — [EXTENDED].

    `signature` is base64 of the signature over the raw UTF-8 challenge string:
    DER-encoded for ES256, raw 64 bytes for ED25519.
    """

    device_id: str = Field(max_length=255)
    signature: str = Field(description="base64 signature over the challenge")


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


class ProfileUpdateRequest(BaseModel):
    """PUT /users/me/profile — spec #13.

    PUT replaces the mutable profile entirely (spec §2), so an omitted field is
    cleared rather than preserved.

    `phone` is settable but lands **unverified** (`is_phone_verified: false`).
    A rider needs a number to call, so it must be capturable at registration,
    but merely typing a number proves nothing — verifying it is a separate OTP
    round trip. `email` is NOT settable here: it is the login identifier, and
    changing it without re-verification would let anyone move an account to an
    address they control.
    """

    full_name: str | None = Field(default=None, max_length=150)
    avatar_url: str | None = Field(default=None, max_length=2048)
    phone: str | None = Field(
        default=None, max_length=20, description="Contact number; stored unverified"
    )


class ChangePasswordRequest(BaseModel):
    """POST /users/me/password — [EXTENDED].

    Requires the current password even though the caller is authenticated: a
    stolen access token must not be enough to lock the real owner out of their
    own account.
    """

    current_password: str | None = Field(
        default=None, description="Required when the account already has a password"
    )
    new_password: str = Field(min_length=8, max_length=128)


class LogoutRequest(BaseModel):
    """POST /auth/logout — [EXTENDED]."""

    refresh_token: str | None = Field(
        default=None, description="Session to end. Omit when using all_devices."
    )
    all_devices: bool = Field(default=False, description="Revoke every active session")
