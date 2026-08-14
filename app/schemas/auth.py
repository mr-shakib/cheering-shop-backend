"""Auth response models."""

from pydantic import BaseModel, Field


class TokenPair(BaseModel):
    """Spec §1: stateless access/refresh pair over `Authorization: Bearer`."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class TwoFactorRequired(BaseModel):
    """Spec §4/§10: login intercepted because `is_2fa_enabled` is true.

    Deliberately carries NO access token. The temp_token is typed `temp_2fa`
    and is only accepted by POST /auth/login/2fa.
    """

    requires_2fa: bool = True
    temp_token: str
    expires_in: int


class UserProfile(BaseModel):
    id: str
    role: str
    email: str | None = None
    phone: str | None = None
    full_name: str | None = None
    avatar_url: str | None = None
    is_email_verified: bool
    is_phone_verified: bool


class AuthResult(BaseModel):
    """What a completed authentication returns."""

    tokens: TokenPair
    user: UserProfile


class MessageResult(BaseModel):
    message: str


class SecurityState(BaseModel):
    """Spec #9: GET /users/me/security"""

    is_2fa_enabled: bool
    is_biometrics_enabled: bool
    biometric_device_count: int = 0
    has_password: bool = True


class TotpProvisioning(BaseModel):
    """Spec #10: POST /auth/2fa/generate"""

    secret: str
    qr_code_url: str = Field(description="otpauth:// URI for the authenticator app")
