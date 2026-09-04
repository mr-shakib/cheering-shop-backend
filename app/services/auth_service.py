"""Authentication business logic: signup, login, 2FA, password reset, biometrics."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.errors import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.security import (
    build_totp_uri,
    create_temp_2fa_token,
    decode_token,
    generate_totp_secret,
    hash_password,
    verify_password,
    verify_totp,
)
from app.models.enums import UserRole
from app.models.user import AuthIdentity, BiometricCredential, User
from app.schemas.auth import SecurityState, TotpProvisioning, UserProfile

log = structlog.get_logger()


def to_profile(user: User) -> UserProfile:
    return UserProfile(
        id=str(user.id),
        role=str(user.role),
        email=user.email,
        phone=user.phone,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        is_email_verified=user.is_email_verified,
        is_phone_verified=user.is_phone_verified,
    )


def _is_email(identifier: str) -> bool:
    return "@" in identifier


async def find_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    """Look a user up by email or phone.

    `users.email` is `citext`, so equality is already case-insensitive at the
    database level — no `lower()` wrapper, which would also defeat the index.
    """
    column = User.email if _is_email(identifier) else User.phone
    result = await db.execute(select(User).where(column == identifier))
    return result.scalar_one_or_none()


async def upsert_provisional_user(db: AsyncSession, identifier: str, role: UserRole) -> User:
    """Spec §4: `/auth/otp/send` "upserts a provisional user".

    The account exists but is unverified and has no password, so it cannot be
    logged into until an OTP is redeemed.

    SELECT-then-INSERT is a race: two simultaneous first-time signups for the
    same address both see nothing, both insert, and the loser hits the unique
    index on users.email — a 500 for a user who merely double-tapped "send
    code". The insert runs in a SAVEPOINT so that violation can be caught
    without poisoning the surrounding transaction, then the winner's row is
    read back.

    Doing this in application code rather than ON CONFLICT because the target
    index differs by identifier type (email vs phone), and the constraint is
    the authority either way.
    """
    existing = await find_by_identifier(db, identifier)
    if existing is not None:
        return existing

    user = User(
        role=role.value,
        email=identifier if _is_email(identifier) else None,
        phone=None if _is_email(identifier) else identifier,
    )
    try:
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError:
        # Someone else created it microseconds ago. The savepoint rolled back,
        # so the session is still usable and their row is now visible.
        log.info("provisional_user_race_resolved", identifier_hint=identifier[-4:])
        winner = await find_by_identifier(db, identifier)
        if winner is None:  # pragma: no cover - would mean a different constraint
            raise
        return winner

    log.info("provisional_user_created", user_id=str(user.id), role=role.value)
    return user


async def link_or_create_google_user(
    db: AsyncSession,
    *,
    subject: str,
    email: str,
    email_verified: bool,
    full_name: str | None = None,
    avatar_url: str | None = None,
) -> User:
    """Resolve a verified Google profile to a local account.

    Three cases, in the order they are tried:

    1. **The Google account is already linked.** Matched on `subject`, never on
       email — see the note on `auth_identities`. Returns that user whatever
       their email says today.
    2. **An account already exists with this email.** Linked automatically, but
       only when Google reports the address verified. That claim is the whole
       basis for the merge: it proves control of the mailbox, which is exactly
       the proof the OTP flow demands before it will trust an address. Without
       it, a provider that let an unverified address through would hand over
       any account whose email an attacker could guess.
    3. **Nobody matches.** A new CUSTOMER is created. Only CUSTOMER, because
       vendors are gated on an application an administrator reviews and riders
       and admins are created out of band -- letting a Google sign-in mint
       either would route around that gate entirely. An existing vendor whose
       email matches still links fine under case 2; it is *creation* that is
       restricted, not access.
    """
    existing_link = await db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == "google", AuthIdentity.subject == subject
        )
    )
    link = existing_link.scalar_one_or_none()

    if link is not None:
        user = await db.get(User, link.user_id)
        if user is None:  # pragma: no cover - FK is ON DELETE CASCADE
            raise UnauthorizedError("This account no longer exists")
        _reject_if_inactive(user)
        link.last_login_at = datetime.now(UTC)
        link.email = email
        _backfill_profile(user, full_name=full_name, avatar_url=avatar_url)
        return user

    if not email_verified:
        # Refused for both remaining cases. Linking is unsafe for the reason
        # above, and creating an account on an address nobody has proven
        # control of would let one person squat another's future signup.
        log.warning("google_email_unverified", subject_hint=subject[-6:])
        raise ValidationError(
            "This Google account's email address is not verified. "
            "Verify it with Google, then try again."
        )

    user = await find_by_identifier(db, email)

    if user is None:
        user = User(
            role=UserRole.CUSTOMER.value,
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
            # Google verified it, and re-verifying with our own OTP would ask
            # the user to prove something we already have proof of.
            is_email_verified=True,
        )
        db.add(user)
    else:
        _reject_if_inactive(user)
        user.is_email_verified = True
        _backfill_profile(user, full_name=full_name, avatar_url=avatar_url)

    # SELECT-then-INSERT is a race on both unique constraints: a user
    # double-tapping "Sign in with Google" can have two callbacks in flight.
    # The savepoint lets the loser be caught without poisoning the surrounding
    # transaction, exactly as in upsert_provisional_user.
    try:
        async with db.begin_nested():
            await db.flush()
            db.add(
                AuthIdentity(
                    user_id=user.id,
                    provider="google",
                    subject=subject,
                    email=email,
                    last_login_at=datetime.now(UTC),
                )
            )
            await db.flush()
    except IntegrityError:
        log.info("google_link_race_resolved", subject_hint=subject[-6:])
        winner = await db.execute(
            select(AuthIdentity).where(
                AuthIdentity.provider == "google", AuthIdentity.subject == subject
            )
        )
        won = winner.scalar_one_or_none()
        if won is None:  # pragma: no cover - would mean a different constraint
            raise
        resolved = await db.get(User, won.user_id)
        if resolved is None:  # pragma: no cover
            raise
        return resolved

    log.info("google_identity_linked", user_id=str(user.id), role=str(user.role))
    return user


def _reject_if_inactive(user: User) -> None:
    if not user.is_active:
        raise UnauthorizedError("This account has been deactivated")


def _backfill_profile(user: User, *, full_name: str | None, avatar_url: str | None) -> None:
    """Fill blanks from the Google profile, never overwrite.

    A user who set their own display name or uploaded an avatar should not have
    it silently replaced by their Google one on every sign-in.
    """
    if full_name and not user.full_name:
        user.full_name = full_name
    if avatar_url and not user.avatar_url:
        user.avatar_url = avatar_url


async def linked_providers(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """Which federated logins this account has, for GET /users/me/security."""
    result = await db.execute(
        select(AuthIdentity.provider).where(AuthIdentity.user_id == user_id)
    )
    return sorted(result.scalars().all())


async def mark_identifier_verified(db: AsyncSession, user: User, identifier: str) -> None:
    if _is_email(identifier):
        user.is_email_verified = True
    else:
        user.is_phone_verified = True


async def authenticate(db: AsyncSession, identifier: str, password: str) -> User:
    """Validate credentials. Raises UnauthorizedError on any failure.

    Every failure path returns the SAME message. Distinguishing "no such user"
    from "wrong password" turns login into an account-enumeration oracle.
    """
    generic = "Invalid credentials"
    user = await find_by_identifier(db, identifier)

    if user is None or user.password_hash is None:
        # Hash a dummy password anyway so a missing account is not detectably
        # faster than a wrong password. Argon2 takes ~50ms; skipping it here
        # would leak account existence through response timing.
        hash_password("timing-equalisation-placeholder")
        raise UnauthorizedError(generic, code=ErrorCode.INVALID_CREDENTIALS)

    if not verify_password(password, user.password_hash):
        raise UnauthorizedError(generic, code=ErrorCode.INVALID_CREDENTIALS)

    if not user.is_active:
        raise UnauthorizedError("This account has been deactivated")

    return user


def issue_2fa_challenge(user: User) -> dict:
    """Spec §10: withhold access tokens and issue an intermediate token."""
    return {
        "requires_2fa": True,
        "temp_token": create_temp_2fa_token(str(user.id)),
        "expires_in": settings.TEMP_2FA_TOKEN_TTL_MINUTES * 60,
    }


async def complete_2fa_login(db: AsyncSession, temp_token: str, code: str) -> User:
    """Spec #4: exchange temp_token + TOTP code for a real session."""
    payload = decode_token(temp_token, expected_type="temp_2fa")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedError("Account is no longer active")
    if not user.is_2fa_enabled or user.totp_secret is None:
        raise ValidationError("Two-factor authentication is not enabled for this account")

    if not verify_totp(decrypt_secret(user.totp_secret), code):
        raise UnauthorizedError("Invalid authentication code", code=ErrorCode.INVALID_CREDENTIALS)

    user.last_login_at = datetime.now(UTC)
    return user


async def set_password(db: AsyncSession, user: User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    await db.flush()


async def change_password(
    db: AsyncSession, user: User, new_password: str, current_password: str | None
) -> None:
    """Change the password of an already-authenticated user.

    If the account HAS a password, the current one is required — an access token
    alone must not let an attacker lock the owner out. If it has none (an
    OTP-only signup), this is the user setting one for the first time and there
    is nothing to verify against.
    """
    if user.password_hash is not None:
        if not current_password:
            raise ValidationError("Current password is required")
        if not verify_password(current_password, user.password_hash):
            raise UnauthorizedError(
                "Current password is incorrect", code=ErrorCode.INVALID_CREDENTIALS
            )
    await set_password(db, user, new_password)
    log.info("password_changed", user_id=str(user.id))


async def update_profile(
    db: AsyncSession,
    user: User,
    full_name: str | None,
    avatar_url: str | None,
    phone: str | None = None,
) -> User:
    """Spec #13. PUT semantics: omitted fields are cleared, not preserved.

    Setting a phone number resets `is_phone_verified` — typing a number is not
    evidence of owning it. `users.phone` is UNIQUE, so a number already
    attached to another account raises 409 rather than a 500 from the
    constraint.
    """
    user.full_name = full_name
    user.avatar_url = avatar_url

    normalised = phone.strip().replace(" ", "") if phone else None
    if normalised != user.phone:
        if normalised:
            result = await db.execute(
                select(User).where(User.phone == normalised, User.id != user.id)
            )
            if result.scalar_one_or_none() is not None:
                raise ConflictError("That phone number is already in use")
        user.phone = normalised
        # A new number starts unverified, even if the old one was verified.
        user.is_phone_verified = False

    await db.flush()
    return user


# ---------------------------------------------------------------------------
# TOTP 2FA
# ---------------------------------------------------------------------------
async def generate_totp(db: AsyncSession, user: User) -> TotpProvisioning:
    """Spec #10.

    Written to `totp_pending_secret`, not `totp_secret`. Promoting it before the
    user proves they can generate a code would lock them out of their own
    account if their authenticator app failed to save it.
    """
    if user.is_2fa_enabled:
        raise ConflictError("Two-factor authentication is already enabled")

    secret = generate_totp_secret()
    user.totp_pending_secret = encrypt_secret(secret)
    await db.flush()

    account = user.email or user.phone or str(user.id)
    return TotpProvisioning(secret=secret, qr_code_url=build_totp_uri(secret, account))


async def enable_totp(db: AsyncSession, user: User, code: str) -> None:
    """Spec #11: promote the pending secret once verified."""
    if user.is_2fa_enabled:
        raise ConflictError("Two-factor authentication is already enabled")
    if user.totp_pending_secret is None:
        raise ValidationError("Call /auth/2fa/generate before enabling")

    secret = decrypt_secret(user.totp_pending_secret)
    if not verify_totp(secret, code):
        raise ValidationError("Incorrect authentication code")

    # Order matters: the CHECK constraint ck_users_2fa_secret refuses a row with
    # is_2fa_enabled and no totp_secret, so both must move together.
    user.totp_secret = user.totp_pending_secret
    user.totp_pending_secret = None
    user.is_2fa_enabled = True
    await db.flush()
    log.info("2fa_enabled", user_id=str(user.id))


async def disable_totp(db: AsyncSession, user: User, code: str) -> None:
    """Spec #12.

    Requires a current TOTP code. Disabling 2FA with a stolen access token alone
    would make the second factor worthless — the whole point is that the
    attacker cannot produce this code.
    """
    if not user.is_2fa_enabled or user.totp_secret is None:
        raise ValidationError("Two-factor authentication is not enabled")

    if not verify_totp(decrypt_secret(user.totp_secret), code):
        raise ValidationError("Incorrect authentication code")

    user.is_2fa_enabled = False
    user.totp_secret = None
    user.totp_pending_secret = None
    await db.flush()
    log.info("2fa_disabled", user_id=str(user.id))


# ---------------------------------------------------------------------------
# Biometrics
# ---------------------------------------------------------------------------
async def enable_biometrics(
    db: AsyncSession,
    user: User,
    device_id: str,
    public_key: str,
    device_name: str | None,
    algorithm: str = "ES256",
) -> None:
    """Spec #7: register a device-bound public key.

    The flag alone would be meaningless — the server must hold a key to verify
    the signed challenge the device returns at login.
    """
    result = await db.execute(
        select(BiometricCredential).where(
            BiometricCredential.user_id == user.id,
            BiometricCredential.device_id == device_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.public_key = public_key
        existing.device_name = device_name
        existing.algorithm = algorithm
        # Re-enrolling clears a lockout: the user proved themselves with a real
        # session to get here.
        existing.failed_attempts = 0
    else:
        db.add(
            BiometricCredential(
                user_id=user.id,
                device_id=device_id,
                device_name=device_name,
                public_key=public_key,
                algorithm=algorithm,
            )
        )

    user.is_biometrics_enabled = True
    await db.flush()


async def disable_biometrics(db: AsyncSession, user: User, device_id: str | None = None) -> int:
    """Spec #8. Without `device_id`, unenrolls every device."""
    from sqlalchemy import delete

    stmt = delete(BiometricCredential).where(BiometricCredential.user_id == user.id)
    if device_id:
        stmt = stmt.where(BiometricCredential.device_id == device_id)
    result = await db.execute(stmt)

    remaining = await db.scalar(
        select(func.count())
        .select_from(BiometricCredential)
        .where(BiometricCredential.user_id == user.id)
    )
    user.is_biometrics_enabled = bool(remaining)
    await db.flush()
    return result.rowcount or 0


async def get_security_state(db: AsyncSession, user: User) -> SecurityState:
    """Spec #9."""
    count = await db.scalar(
        select(func.count())
        .select_from(BiometricCredential)
        .where(BiometricCredential.user_id == user.id)
    )
    return SecurityState(
        is_2fa_enabled=user.is_2fa_enabled,
        is_biometrics_enabled=user.is_biometrics_enabled,
        biometric_device_count=count or 0,
        has_password=user.password_hash is not None,
        linked_providers=await linked_providers(db, user.id),
    )


async def require_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user
