"""Biometric login: challenge issue and signature verification.

Enrolment (`/auth/biometrics/enable`) stores a device-bound public key. Until
now nothing ever read it — there was no way to *log in* with a biometric, so the
feature was inert. This closes that.

The flow is a standard signed-challenge handshake:

    1. client  -> POST /auth/biometrics/challenge {device_id}
    2. server  -> {challenge}                       (random nonce, 2-minute TTL)
    3. device  -- Face ID / fingerprint unlocks the private key in the
                  Secure Enclave / Keystore, which signs the nonce
    4. client  -> POST /auth/biometrics/login {device_id, signature}
    5. server  -- verifies against the enrolled public key, issues tokens

The biometric itself never leaves the device and is never sent to us; possession
of a private key that only a successful biometric can unlock IS the proof.

**Mobile contract — the client must match this exactly:**

* `public_key` is base64-encoded **DER SubjectPublicKeyInfo**
  (iOS: `SecKeyCopyExternalRepresentation` needs wrapping into SPKI;
   Android: `KeyStore` → `PublicKey.getEncoded()` is already SPKI).
* `ES256` — ECDSA over P-256, SHA-256 digest, **DER-encoded** signature.
  This is the only algorithm the iOS Secure Enclave supports.
* `ED25519` — raw 64-byte signature. Android Keystore or a software key.
* The signed message is the **raw UTF-8 challenge string**, not a hash of it and
  not the base64 of it.
"""

import base64
import secrets

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode, UnauthorizedError, ValidationError
from app.core.redis import get_redis
from app.models.enums import BiometricAlgorithm
from app.models.user import BiometricCredential, User

log = structlog.get_logger()

CHALLENGE_KEY = "biometric:challenge:{device_id}"
CHALLENGE_TTL_SECONDS = 120
MAX_FAILED_ATTEMPTS = 5


async def issue_challenge(device_id: str) -> tuple[str, int]:
    """Mint a single-use nonce for this device.

    Unauthenticated on purpose — the whole point is to log in without a session.
    It leaks nothing: the response is random bytes, identical whether or not the
    device is enrolled, so it cannot be used to probe which devices exist.
    """
    challenge = secrets.token_urlsafe(32)
    await get_redis().setex(
        CHALLENGE_KEY.format(device_id=device_id), CHALLENGE_TTL_SECONDS, challenge
    )
    return challenge, CHALLENGE_TTL_SECONDS


def _verify_signature(credential: BiometricCredential, challenge: str, signature: bytes) -> bool:
    """Check `signature` over `challenge` against the enrolled public key."""
    try:
        public_key = serialization.load_der_public_key(base64.b64decode(credential.public_key))
    except Exception as exc:
        # Enrolment accepted something unusable. Better to fail closed and log
        # than to let a malformed key silently authenticate nobody forever.
        log.error("biometric_bad_public_key", credential_id=str(credential.id), error=str(exc))
        return False

    message = challenge.encode()
    try:
        if credential.algorithm == BiometricAlgorithm.ES256:
            if not isinstance(public_key, ec.EllipticCurvePublicKey):
                return False
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        elif credential.algorithm == BiometricAlgorithm.ED25519:
            if not isinstance(public_key, ed25519.Ed25519PublicKey):
                return False
            public_key.verify(signature, message)
        else:  # pragma: no cover - enum is closed
            return False
    except (InvalidSignature, ValueError):
        return False
    return True


async def authenticate(db: AsyncSession, device_id: str, signature_b64: str) -> User:
    """Complete a biometric login. Raises UnauthorizedError on any failure.

    Every rejection returns the same message: distinguishing "device unknown"
    from "bad signature" would let an attacker enumerate enrolled devices.
    """
    generic = "Biometric authentication failed"
    redis = get_redis()
    key = CHALLENGE_KEY.format(device_id=device_id)

    # Consume the nonce before verifying, so a replayed signature cannot be
    # retried against the same challenge even on failure.
    challenge = await redis.getdel(key)
    if challenge is None:
        raise UnauthorizedError(
            "Challenge expired or already used", code=ErrorCode.INVALID_CREDENTIALS
        )

    result = await db.execute(
        select(BiometricCredential).where(BiometricCredential.device_id == device_id)
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise UnauthorizedError(generic, code=ErrorCode.INVALID_CREDENTIALS)

    if credential.failed_attempts >= MAX_FAILED_ATTEMPTS:
        raise UnauthorizedError(
            "This device is locked. Sign in with your password to re-enrol.",
            code=ErrorCode.FORBIDDEN,
        )

    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception as exc:
        raise ValidationError("signature must be base64") from exc

    if not _verify_signature(credential, challenge, signature):
        credential.failed_attempts += 1
        await db.commit()
        log.warning(
            "biometric_verify_failed",
            device_id=device_id,
            failed_attempts=credential.failed_attempts,
        )
        raise UnauthorizedError(generic, code=ErrorCode.INVALID_CREDENTIALS)

    user = await db.get(User, credential.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(generic, code=ErrorCode.INVALID_CREDENTIALS)

    # A biometric proves the device, not a second factor. If the account has 2FA
    # switched on, the caller must still complete it — otherwise enrolling a
    # device would be a way to bypass 2FA entirely.
    from datetime import UTC, datetime

    credential.failed_attempts = 0
    credential.last_used_at = datetime.now(UTC)
    await db.flush()
    return user
