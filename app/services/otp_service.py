"""OTP issue and verification, with Redis-backed rate limiting.

Spec §4 requires `POST /auth/otp/send` to return 429 when rate limited. Two
independent limits are enforced, because they defend against different attacks:

* **Send cooldown** — stops an attacker using your SMS budget as a weapon
  (SMS pumping) and stops a victim being spammed.
* **Verify attempts** — a 6-digit code is 1,000,000 candidates. Without an
  attempt cap, an attacker walks the space in minutes.
"""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ErrorCode, RateLimitedError, ValidationError
from app.core.redis import get_redis
from app.core.security import generate_otp, hash_otp, verify_otp
from app.models.enums import OtpPurpose
from app.models.user import OtpCode
from app.services import email_service

log = structlog.get_logger()

_COOLDOWN_KEY = "otp:cooldown:{purpose}:{identifier}"


def normalise_identifier(identifier: str) -> str:
    """Emails are case-insensitive; phone numbers are not, but stray whitespace
    is a common client bug. Normalising here keeps rate-limit keys and the
    `otp_codes.identifier` lookup consistent."""
    value = identifier.strip()
    return value.lower() if "@" in value else value.replace(" ", "")


def _is_email(identifier: str) -> bool:
    return "@" in identifier


async def _deliver(identifier: str, code: str, purpose: OtpPurpose) -> None:
    """Dispatch the code over whichever channel the identifier implies.

    Delivery failures are logged and swallowed. Two reasons: the code is already
    stored (so a retry via resend works), and propagating a provider error to
    `/auth/password/forgot` would reveal whether the account exists — the exact
    enumeration leak that endpoint is written to prevent.
    """
    if not _is_email(identifier):
        # SMS is a separate provider decision; see docs/email-setup-resend.md.
        log.warning("otp_sms_not_configured", purpose=purpose.value)
        return

    builder = (
        email_service.password_reset_otp
        if purpose is OtpPurpose.PASSWORD_RESET
        else email_service.signup_otp
    )
    subject, html, text = builder(code)
    try:
        await email_service.send_email(identifier, subject, html, text)
    except Exception as exc:
        log.error("otp_delivery_failed", purpose=purpose.value, error=str(exc))


async def send_otp(db: AsyncSession, identifier: str, purpose: OtpPurpose) -> str:
    """Generate, store and dispatch an OTP.

    Returns the plaintext code so local/test callers can echo it. A DEPLOYED
    caller must never include it in the response — it goes to the user's inbox
    only. See `settings.expose_debug_secrets`.
    """
    identifier = normalise_identifier(identifier)
    redis = get_redis()
    key = _COOLDOWN_KEY.format(purpose=purpose.value, identifier=identifier)

    if await redis.exists(key):
        ttl = await redis.ttl(key)
        raise RateLimitedError(
            f"Please wait {max(ttl, 1)} seconds before requesting another code",
            headers={"Retry-After": str(max(ttl, 1))},
        )

    code = generate_otp()
    db.add(
        OtpCode(
            identifier=identifier,
            purpose=purpose.value,
            code_hash=hash_otp(code, identifier),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.OTP_TTL_SECONDS),
        )
    )
    await db.flush()

    await redis.setex(key, settings.OTP_RESEND_COOLDOWN_SECONDS, "1")
    log.info("otp_issued", purpose=purpose.value, identifier_hint=identifier[-4:])

    await _deliver(identifier, code, purpose)
    return code


async def verify_and_consume(
    db: AsyncSession, identifier: str, code: str, purpose: OtpPurpose
) -> None:
    """Validate an OTP and burn it. Raises on any failure."""
    identifier = normalise_identifier(identifier)

    result = await db.execute(
        select(OtpCode)
        .where(
            OtpCode.identifier == identifier,
            OtpCode.purpose == purpose.value,
            OtpCode.consumed_at.is_(None),
        )
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()

    if row is None:
        raise ValidationError("No pending code for this identifier", code=ErrorCode.INVALID_OTP)

    if row.expires_at <= datetime.now(UTC):
        raise ValidationError("This code has expired", code=ErrorCode.INVALID_OTP)

    if row.attempts >= settings.OTP_MAX_ATTEMPTS:
        # Burn it rather than leaving a locked row that blocks reissue.
        row.consumed_at = datetime.now(UTC)
        await db.commit()
        raise RateLimitedError("Too many incorrect attempts. Request a new code")

    if not verify_otp(code, identifier, row.code_hash):
        row.attempts += 1
        await db.commit()
        raise ValidationError("Incorrect code", code=ErrorCode.INVALID_OTP)

    # Single-use: without this, a code stays valid for its whole TTL and can be
    # replayed by anyone who observes it.
    row.consumed_at = datetime.now(UTC)
    await db.flush()
