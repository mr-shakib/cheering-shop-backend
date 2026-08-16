"""Authentication & Security — spec endpoints #1–8, #10–12, plus [EXTENDED] refresh."""

from typing import Annotated

from fastapi import APIRouter, Header, Request, status

from app.api.deps import CurrentUser, DbSession
from app.core import rate_limit
from app.core.client import client_ip
from app.core.config import settings
from app.core.errors import ValidationError
from app.core.responses import ok
from app.models.enums import OtpPurpose, UserRole
from app.schemas.requests import (
    BiometricsEnableRequest,
    Login2FARequest,
    LoginRequest,
    LogoutRequest,
    OtpSendRequest,
    OtpVerifyRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    RefreshRequest,
    TotpEnableRequest,
)
from app.services import auth_service, otp_service, token_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _client_meta(request: Request) -> dict:
    return {
        "user_agent": request.headers.get("user-agent"),
        "ip_address": client_ip(request),
    }


@router.post("/otp/send", summary="Send signup OTP")
async def send_otp(body: OtpSendRequest, db: DbSession):
    """Spec #1. Public. Rate limited — 429 inside the resend cooldown."""
    identifier = otp_service.normalise_identifier(body.identifier)
    await auth_service.upsert_provisional_user(db, identifier, UserRole.CUSTOMER)
    code = await otp_service.send_otp(db, identifier, OtpPurpose.SIGNUP)
    await db.commit()

    payload: dict = {"message": "OTP sent"}
    # Never leak the code from a deployed environment; dispatch is via SES/Twilio.
    if settings.expose_debug_secrets:
        payload["debug_code"] = code
    return ok(payload)


@router.post("/otp/verify", summary="Verify OTP")
async def verify_otp(body: OtpVerifyRequest, request: Request, db: DbSession):
    """Spec #2. Marks the identifier verified and issues a session."""
    identifier = otp_service.normalise_identifier(body.identifier)

    # Two ceilings, because they stop different things. The `attempts` column in
    # otp_codes caps guesses against ONE code; this caps guesses against the
    # identifier across every code it is ever issued. Without the second, an
    # attacker just requests a fresh code each minute and grinds indefinitely —
    # which matters far more at 4 digits than it did at 6.
    await rate_limit.hit(
        rate_limit.otp_verify_key(identifier),
        limit=settings.OTP_VERIFY_MAX_PER_HOUR,
        window_seconds=3600,
    )

    await otp_service.verify_and_consume(db, identifier, body.code, OtpPurpose.SIGNUP)

    user = await auth_service.find_by_identifier(db, identifier)
    if user is None:
        raise ValidationError("No account exists for this identifier")

    await auth_service.mark_identifier_verified(db, user, identifier)

    # Optional, and the only moment a new account can gain a password. Without
    # it the user would have to immediately run the forgot-password flow just to
    # make /auth/login usable.
    if body.password:
        await auth_service.set_password(db, user, body.password)
    if body.full_name:
        user.full_name = body.full_name

    tokens = await token_service.issue_token_pair(db, user, **_client_meta(request))
    await db.commit()
    return ok({"tokens": tokens.model_dump(), "user": auth_service.to_profile(user).model_dump()})


@router.post("/logout", summary="End a session [EXTENDED]")
async def logout(body: LogoutRequest, user: CurrentUser, db: DbSession):
    """**[EXTENDED] — not in the specification.**

    §1 mandates refresh tokens but defines no way to revoke one. Without this, a
    user tapping "log out" only clears local storage: the refresh token stays
    valid for 30 days, so a stolen phone keeps a working session.

    Idempotent — logging out twice is not an error.
    """
    if body.all_devices:
        count = await token_service.revoke_all_for_user(db, user.id)
    else:
        if not body.refresh_token:
            raise ValidationError("refresh_token is required unless all_devices is true")
        count = int(await token_service.revoke_one(db, body.refresh_token, user.id))

    await db.commit()
    return ok({"message": "Signed out", "sessions_revoked": count})


@router.post("/login", summary="Password login")
async def login(body: LoginRequest, request: Request, db: DbSession):
    """Spec #3. Returns a 2FA challenge instead of tokens when 2FA is active.

    Brute-force protected on two independent axes, because they stop different
    attacks:

    * **per identifier** — someone grinding one victim's password;
    * **per source IP** — credential stuffing, spraying one common password
      across thousands of accounts, where no single identifier ever trips its
      own limit.

    A 401 alone is not a defence: without these, an unauthenticated attacker can
    try passwords as fast as the network allows.
    """
    identifier = otp_service.normalise_identifier(body.identifier)
    ip = client_ip(request)

    await rate_limit.hit(
        rate_limit.login_ip_key(ip),
        limit=settings.LOGIN_IP_MAX_ATTEMPTS,
        window_seconds=settings.LOGIN_WINDOW_SECONDS,
    )
    await rate_limit.hit(
        rate_limit.login_identifier_key(identifier),
        limit=settings.LOGIN_MAX_ATTEMPTS,
        window_seconds=settings.LOGIN_WINDOW_SECONDS,
    )

    user = await auth_service.authenticate(db, identifier, body.password)

    # Clear the identifier counter, NOT the IP counter. Resetting the IP budget
    # on success would let an attacker log into their own account between
    # guesses to refresh their allowance indefinitely.
    await rate_limit.reset(rate_limit.login_identifier_key(identifier))

    if user.is_2fa_enabled:
        return ok(auth_service.issue_2fa_challenge(user))

    from datetime import UTC, datetime

    user.last_login_at = datetime.now(UTC)
    tokens = await token_service.issue_token_pair(db, user, **_client_meta(request))
    await db.commit()
    return ok({"tokens": tokens.model_dump(), "user": auth_service.to_profile(user).model_dump()})


@router.post("/login/2fa", summary="Complete 2FA login")
async def login_2fa(body: Login2FARequest, request: Request, db: DbSession):
    """Spec #4."""
    user = await auth_service.complete_2fa_login(db, body.temp_token, body.code)
    tokens = await token_service.issue_token_pair(db, user, **_client_meta(request))
    await db.commit()
    return ok({"tokens": tokens.model_dump(), "user": auth_service.to_profile(user).model_dump()})


@router.post("/refresh", summary="Exchange a refresh token [EXTENDED]")
async def refresh(body: RefreshRequest, request: Request, db: DbSession):
    """**[EXTENDED] — not in the specification.**

    §1 mandates an access/refresh pair but §3 defines no endpoint to redeem one,
    so as specified every user is silently logged out when their 30-minute
    access token expires, with no path back except re-entering their password.

    Tokens are rotated on every use, and presenting an already-revoked token
    revokes the entire session family as suspected theft.
    """
    tokens, user = await token_service.rotate(db, body.refresh_token, **_client_meta(request))
    return ok({"tokens": tokens.model_dump(), "user": auth_service.to_profile(user).model_dump()})


@router.post("/password/forgot", summary="Request password reset")
async def forgot_password(body: PasswordForgotRequest, db: DbSession):
    """Spec #5.

    Always returns 200 with an identical message whether or not the account
    exists — anything else is an account-enumeration oracle.
    """
    identifier = otp_service.normalise_identifier(body.identifier)
    user = await auth_service.find_by_identifier(db, identifier)

    payload: dict = {"message": "If an account exists, a reset code has been sent"}
    if user is not None:
        code = await otp_service.send_otp(db, identifier, OtpPurpose.PASSWORD_RESET)
        await db.commit()
        if settings.expose_debug_secrets:
            payload["debug_code"] = code
    return ok(payload)


@router.post("/password/reset", summary="Reset password")
async def reset_password(body: PasswordResetRequest, db: DbSession):
    """Spec #6.

    Revokes every active session on success. A reset that leaves an attacker's
    existing session alive has not actually locked them out.
    """
    identifier = otp_service.normalise_identifier(body.identifier)
    await otp_service.verify_and_consume(db, identifier, body.code, OtpPurpose.PASSWORD_RESET)

    user = await auth_service.find_by_identifier(db, identifier)
    if user is None:
        raise ValidationError("No account exists for this identifier")

    await auth_service.set_password(db, user, body.new_password)
    revoked = await token_service.revoke_all_for_user(db, user.id)
    await db.commit()
    return ok({"message": "Password updated", "sessions_revoked": revoked})


@router.post("/biometrics/enable", summary="Enable biometric login")
async def enable_biometrics(body: BiometricsEnableRequest, user: CurrentUser, db: DbSession):
    """Spec #7."""
    await auth_service.enable_biometrics(
        db, user, body.device_id, body.public_key, body.device_name
    )
    await db.commit()
    return ok({"message": "Biometric login enabled", "device_id": body.device_id})


@router.delete("/biometrics/disable", summary="Disable biometric login")
async def disable_biometrics(
    user: CurrentUser,
    db: DbSession,
    device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
):
    """Spec #8. Omit the header to unenrol every device."""
    removed = await auth_service.disable_biometrics(db, user, device_id)
    await db.commit()
    return ok({"message": "Biometric login disabled", "devices_removed": removed})


@router.post("/2fa/generate", summary="Generate TOTP secret")
async def generate_2fa(user: CurrentUser, db: DbSession):
    """Spec #10."""
    provisioning = await auth_service.generate_totp(db, user)
    await db.commit()
    return ok(provisioning.model_dump())


@router.post("/2fa/enable", status_code=status.HTTP_200_OK, summary="Enable TOTP 2FA")
async def enable_2fa(body: TotpEnableRequest, user: CurrentUser, db: DbSession):
    """Spec #11."""
    await auth_service.enable_totp(db, user, body.code)
    await db.commit()
    return ok({"message": "Two-factor authentication enabled", "is_2fa_enabled": True})


@router.post("/2fa/disable", summary="Disable TOTP 2FA")
async def disable_2fa(body: TotpEnableRequest, user: CurrentUser, db: DbSession):
    """Spec #12. Requires a current TOTP code, not just a valid session."""
    await auth_service.disable_totp(db, user, body.code)
    await db.commit()
    return ok({"message": "Two-factor authentication disabled", "is_2fa_enabled": False})
