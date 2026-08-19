"""Authentication: OTP, login, passwords, biometrics, 2FA, sessions."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.requests.base import _IdentifierBody


class OtpSendRequest(_IdentifierBody):
    """POST /auth/otp/send

    `role` decides what kind of account the provisional user gets. Only the two
    self-service roles are accepted: RIDER and ADMIN accounts are created by an
    administrator, never by whoever happens to hit this endpoint.

    A role is fixed at creation. If the address already exists under a different
    role, registration returns 409 rather than silently switching it — the
    composite role-guard foreign keys make a live role change unsafe once the
    account owns anything.
    """

    role: Literal["CUSTOMER", "VENDOR"] = "CUSTOMER"


class OtpVerifyRequest(_IdentifierBody):
    """POST /auth/otp/verify

    `password` is optional and is the ONLY point at which a brand-new account
    can acquire one. Without it, `/auth/login` is unreachable for a new user:
    the only other path to `set_password` is `/auth/password/reset`, which
    itself needs an OTP. Supplying it here turns signup into a single round
    trip instead of signup-then-immediately-reset.
    """

    code: str = Field(min_length=4, max_length=8)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=150)


class LoginRequest(_IdentifierBody):
    """POST /auth/login"""

    password: str = Field(min_length=8)


class Login2FARequest(BaseModel):
    """POST /auth/login/2fa"""

    temp_token: str
    code: str = Field(min_length=6, max_length=6)


class PasswordForgotRequest(_IdentifierBody):
    """POST /auth/password/forgot"""


class PasswordResetRequest(_IdentifierBody):
    """POST /auth/password/reset

    The spec shows a bare `token`. We use identifier + the OTP code issued by
    /auth/password/forgot instead: it reuses the same rate-limited, attempt-
    capped, single-use OTP machinery rather than introducing a second
    credential type with its own expiry and revocation rules.
    """

    code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8)


class RefreshRequest(BaseModel):
    """POST /auth/refresh — [EXTENDED], see the endpoint docstring."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """POST /auth/logout — [EXTENDED]."""

    refresh_token: str | None = Field(
        default=None, description="Session to end. Omit when using all_devices."
    )
    all_devices: bool = Field(default=False, description="Revoke every active session")


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
