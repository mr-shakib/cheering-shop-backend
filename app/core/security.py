"""Cryptographic primitives: passwords, JWTs, TOTP, OTP codes, rider PINs.

Choices verified against CPython 3.14 before being written down:

* **Argon2id** for passwords, via argon2-cffi directly. The usual
  ``passlib[bcrypt]`` recipe is broken on this stack — bcrypt 5.0 removed the
  ``__about__`` attribute passlib 1.7.4 probes for, so ``CryptContext`` raises
  ``MissingBackendError`` at runtime even though the import succeeds.
* **HMAC-SHA256, not a slow KDF, for rider PINs and OTPs.** These are 4–6 digit
  secrets: 10k–1M candidates fall to brute force in seconds regardless of KDF
  cost, so paying Argon2 latency on every handoff buys nothing. What actually
  protects them is a server-side pepper (a stolen database is useless without
  it), a short TTL, and an attempt counter.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings
from app.core.errors import UnauthorizedError

TokenType = Literal["access", "refresh", "temp_2fa", "password_reset"]

# OWASP-recommended Argon2id parameters.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when stored parameters are weaker than current policy."""
    return _hasher.check_needs_rehash(password_hash)


# ---------------------------------------------------------------------------
# JWT (spec §1: stateless access/refresh pair over Bearer)
# ---------------------------------------------------------------------------
def _create_token(subject: str, token_type: TokenType, ttl: timedelta, **claims: Any) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_urlsafe(16),
        **claims,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str, role: str, **claims: Any) -> str:
    return _create_token(
        user_id,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES),
        role=role,
        **claims,
    )


def create_refresh_token(user_id: str, **claims: Any) -> str:
    return _create_token(
        user_id, "refresh", timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS), **claims
    )


def create_temp_2fa_token(user_id: str) -> str:
    """Issued when login is intercepted by 2FA (spec §4).

    Carries no role claim and is typed `temp_2fa`, so it cannot be replayed
    against a normal authenticated endpoint even before it expires.
    """
    return _create_token(
        user_id, "temp_2fa", timedelta(minutes=settings.TEMP_2FA_TOKEN_TTL_MINUTES)
    )


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token has expired", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid token") from exc

    # Without this check an access token would be accepted wherever a refresh
    # token is expected, and vice versa.
    if expected_type and payload.get("type") != expected_type:
        raise UnauthorizedError("Invalid token type for this operation")
    return payload


def hash_refresh_token(token: str) -> str:
    """Refresh tokens are stored hashed, so a table dump yields nothing usable."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# OTP (spec §4: /auth/otp/*)
# ---------------------------------------------------------------------------
def generate_otp(length: int | None = None) -> str:
    n = length or settings.OTP_LENGTH
    return "".join(secrets.choice("0123456789") for _ in range(n))


def hash_otp(code: str, identifier: str) -> str:
    """Peppered and scoped to the identifier, so digests cannot be shared."""
    msg = f"{identifier}:{code}".encode()
    return hmac.new(settings.OTP_PEPPER.encode(), msg, hashlib.sha256).hexdigest()


def verify_otp(code: str, identifier: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(code, identifier), stored_hash)


# ---------------------------------------------------------------------------
# Rider handoff PIN (decision D3)
# ---------------------------------------------------------------------------
def generate_rider_pin() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(settings.RIDER_PIN_LENGTH))


def hash_rider_pin(pin: str, order_id: str) -> str:
    """HMAC-SHA256(pepper, order_id || pin).

    Scoped by order_id so the same PIN on two orders produces different digests —
    nobody can correlate them, and a leaked digest is useless elsewhere.
    """
    msg = f"{order_id}:{pin}".encode()
    return hmac.new(settings.RIDER_PIN_PEPPER.encode(), msg, hashlib.sha256).hexdigest()


def verify_rider_pin(pin: str, order_id: str, stored_hash: str) -> bool:
    """Constant-time comparison — a timing oracle on a 4-digit space is fatal."""
    return hmac.compare_digest(hash_rider_pin(pin, order_id), stored_hash)


# ---------------------------------------------------------------------------
# TOTP 2FA (spec §4: /auth/2fa/*)
# ---------------------------------------------------------------------------
def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_totp_uri(secret: str, account_name: str, issuer: str | None = None) -> str:
    """otpauth:// URI the client renders as a QR code."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=account_name, issuer_name=issuer or settings.PROJECT_NAME
    )


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """`valid_window=1` tolerates one 30s step of clock drift either side."""
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)
