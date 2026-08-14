"""Favorites — spec endpoints #24–25."""

import uuid

from fastapi import APIRouter

from app.api.deps import CustomerUser, DbSession, Paginated
from app.core.errors import NotImplementedYetError

router = APIRouter(prefix="/users/me/favorites", tags=["Favorites"])


@router.get("", summary="List favorites")
async def list_favorites(user: CustomerUser, db: DbSession, page: Paginated):
    """Spec #24."""
    raise NotImplementedYetError()


@router.post("/{restaurant_id}", summary="Toggle favorite")
async def add_favorite(restaurant_id: uuid.UUID, user: CustomerUser, db: DbSession):
    """Spec #25. Idempotent by composite PK — re-posting is a no-op, not a 409."""
    raise NotImplementedYetError()
