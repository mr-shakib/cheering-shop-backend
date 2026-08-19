"""User self-service: profile, password, addresses, uploads."""

from typing import Literal

from pydantic import BaseModel, Field


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


class PresignedUrlRequest(BaseModel):
    """POST /uploads/presigned-url"""

    file_type: str = Field(description="MIME type, e.g. image/jpeg")
    file_name: str | None = None
