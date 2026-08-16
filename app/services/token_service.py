"""Issuing, rotating and revoking refresh tokens.

Refresh tokens are stored as SHA-256 hashes and **rotated on every use**: each
redemption revokes the presented token and issues a new one, linked via
`replaced_by_id`.

That chain enables reuse detection. A refresh token is a bearer credential with
a 30-day life; if one is stolen, both the attacker and the legitimate user will
eventually redeem the same token. The second redemption is proof of compromise,
and the only safe response is to revoke the whole family — see
`_handle_token_reuse` below.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_refresh_token,
)
from app.models.user import RefreshToken, User
from app.schemas.auth import TokenPair

log = structlog.get_logger()


async def issue_token_pair(
    db: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    replaces: RefreshToken | None = None,
) -> TokenPair:
    """Mint an access/refresh pair and persist the refresh token's hash."""
    access = create_access_token(str(user.id), user.role)
    refresh = create_refresh_token(str(user.id))

    row = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(row)
    await db.flush()

    if replaces is not None:
        replaces.revoked_at = datetime.now(UTC)
        replaces.replaced_by_id = row.id

    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
    )


async def _handle_token_reuse(db: AsyncSession, token_row: RefreshToken) -> None:
    """An already-revoked token was presented: assume theft.

    We cannot tell whether the attacker or the real user is holding the stale
    copy, so every active session for the user is revoked and both are forced to
    log in again. Inconvenient, and far better than leaving a thief with a
    30-day credential.
    """
    log.warning(
        "refresh_token_reuse_detected",
        user_id=str(token_row.user_id),
        token_id=str(token_row.id),
    )
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == token_row.user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()
    raise UnauthorizedError("Session revoked. Please sign in again")


async def rotate(
    db: AsyncSession,
    refresh_token: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[TokenPair, User]:
    """Exchange a refresh token for a new pair."""
    payload = decode_token(refresh_token, expected_type="refresh")

    token_hash = hash_refresh_token(refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    row = result.scalar_one_or_none()

    if row is None:
        # Signature is valid but we have no record: either it was pruned, or the
        # signing key is shared with something it shouldn't be.
        raise UnauthorizedError("Refresh token is not recognised")

    if row.revoked_at is not None:
        await _handle_token_reuse(db, row)

    if row.expires_at <= datetime.now(UTC):
        raise UnauthorizedError("Refresh token has expired", code="TOKEN_EXPIRED")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedError("Account is no longer active")

    pair = await issue_token_pair(
        db, user, user_agent=user_agent, ip_address=ip_address, replaces=row
    )
    await db.commit()
    return pair, user


async def revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Revoke every active session. Used after a password reset.

    A password reset must terminate sessions an attacker already holds —
    otherwise changing the password accomplishes nothing against someone who is
    already inside.
    """
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
        .returning(RefreshToken.id)
    )
    return len(result.fetchall())


async def revoke_one(db: AsyncSession, refresh_token: str, user_id: uuid.UUID) -> bool:
    """Revoke a single session — the logout path.

    Scoped to `user_id` so a caller cannot end somebody else's session by
    presenting a token they happen to have obtained.

    Returns True if a live session was ended. A token that was already revoked,
    or belongs to another user, returns False rather than raising: logout should
    be idempotent, and telling a caller "that token isn't yours" is information
    they should not get.
    """
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(refresh_token),
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    row.revoked_at = datetime.now(UTC)
    await db.flush()
    return True
