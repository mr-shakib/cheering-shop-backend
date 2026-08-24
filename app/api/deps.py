"""Shared route dependencies: authentication, RBAC, pagination, idempotency."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import decode_token
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User

# auto_error=False so a missing header raises OUR envelope, not FastAPI's
# `{"detail": "Not authenticated"}`.
bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    """Resolve the caller from a Bearer access token (spec §1)."""
    if creds is None or not creds.credentials:
        raise UnauthorizedError("Authorization header missing")

    payload = decode_token(creds.credentials, expected_type="access")
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Malformed token")

    user = await db.get(User, uuid.UUID(user_id))
    if user is None:
        raise UnauthorizedError("User no longer exists")
    if not user.is_active:
        raise ForbiddenError("This account has been deactivated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User | None:
    """The caller if they happen to be signed in, otherwise None.

    Discovery is public — a browsing customer must not be forced to log in —
    but a signed-in one should still see their hearts filled and their
    favourites marked. This resolves that without letting authentication
    become a requirement.

    A malformed or expired token yields None rather than a 401, deliberately:
    on a public endpoint the correct response to a stale token is to serve the
    anonymous view, not to break browsing until the client refreshes.
    """
    if creds is None or not creds.credentials:
        return None
    try:
        payload = decode_token(creds.credentials, expected_type="access")
        user_id = payload.get("sub")
        if not user_id:
            return None
        user = await db.get(User, uuid.UUID(user_id))
    except Exception:
        return None
    return user if user is not None and user.is_active else None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_roles(*roles: UserRole):
    """RBAC guard implementing the spec §7 permission matrix.

    Usage: ``dependencies=[Depends(require_roles(UserRole.VENDOR))]``
    """
    allowed: set[str] = {r.value for r in roles}

    async def _guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise ForbiddenError(f"This endpoint requires one of: {', '.join(sorted(allowed))}")
        return user

    return _guard


# Convenience aliases for the four actors.
CustomerUser = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]
VendorUser = Annotated[User, Depends(require_roles(UserRole.VENDOR))]
RiderUser = Annotated[User, Depends(require_roles(UserRole.RIDER))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


async def get_vendor_restaurant(db: DbSession, user: VendorUser) -> Restaurant:
    """Resolve the calling vendor's restaurant. **Decision D1's hedge.**

    Every vendor endpoint MUST obtain its restaurant through this dependency and
    never by querying ``owner_id`` inline. The schema currently enforces one
    restaurant per vendor (``UNIQUE(owner_id)``), but that constraint is cheap to
    drop — what is expensive is a breaking API change for shipped mobile
    clients. Concentrating resolution here means multi-outlet support later
    costs one migration and one function body, not a rewrite of twelve
    endpoints.

    Vendor responses must also echo ``restaurant_id`` so clients already carry
    it when that day comes.
    """
    result = await db.execute(select(Restaurant).where(Restaurant.owner_id == user.id))
    restaurant = result.scalar_one_or_none()
    if restaurant is None:
        raise NotFoundError("No restaurant is registered to this vendor account")
    return restaurant


VendorRestaurant = Annotated[Restaurant, Depends(get_vendor_restaurant)]


# ---------------------------------------------------------------------------
# Pagination & sorting (spec §2: ?limit=20&offset=0&sort=-created_at)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Pagination:
    limit: int
    offset: int
    sort: str | None = None

    def order_by(self, model: type, allowed: Sequence[str], default: str):
        """Translate `?sort=-created_at` into a SQLAlchemy ordering.

        `allowed` is a whitelist: without it, a caller could sort by any column,
        including unindexed ones, and turn a cheap query into a table scan.
        """
        field, descending = default.lstrip("-"), default.startswith("-")
        if self.sort:
            candidate = self.sort.lstrip("-")
            if candidate in allowed:
                field, descending = candidate, self.sort.startswith("-")
        column = getattr(model, field)
        return column.desc() if descending else column.asc()


def pagination_params(
    limit: Annotated[int, Query(ge=1, le=settings.MAX_PAGE_LIMIT)] = settings.DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[str | None, Query(description="e.g. -created_at")] = None,
) -> Pagination:
    return Pagination(limit=limit, offset=offset, sort=sort)


Paginated = Annotated[Pagination, Depends(pagination_params)]


# ---------------------------------------------------------------------------
# Idempotency (spec §9)
# ---------------------------------------------------------------------------
async def idempotency_key(
    request: Request,
    key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    """Surface the Idempotency-Key header.

    Required on POST /orders so a retry over a flaky cellular connection cannot
    create a second order. Enforcement lands with the Orders module in Step 4.
    """
    _ = request
    return key


IdempotencyKey = Annotated[str | None, Depends(idempotency_key)]
