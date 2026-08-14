"""Symmetric encryption for secrets that must be recoverable, not hashed.

A TOTP secret cannot be hashed: the server has to reproduce it on every login to
compute the expected code. So it is encrypted at rest instead. If the database
leaks without the application's key, the attacker gets ciphertext and cannot
generate valid 2FA codes.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


@lru_cache
def _fernet() -> Fernet:
    """Derive a valid Fernet key from whatever the operator configured.

    Fernet requires exactly 32 url-safe base64 bytes. `openssl rand -hex 32`
    produces a 64-character hex string, which is NOT that. Hashing to a fixed
    32 bytes accepts any sufficiently random input without asking operators to
    remember a specific encoding.
    """
    digest = hashlib.sha256(settings.TOTP_ENCRYPTION_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        # Almost always means TOTP_ENCRYPTION_KEY was rotated without
        # re-encrypting stored secrets. Fail loudly — silently treating this as
        # "2FA disabled" would be a security regression.
        raise RuntimeError(
            "Unable to decrypt stored TOTP secret. Has TOTP_ENCRYPTION_KEY changed?"
        ) from exc
