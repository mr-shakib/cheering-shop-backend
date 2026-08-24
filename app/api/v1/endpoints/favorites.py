"""Favorites — spec endpoint #34."""

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.responses import ok
from app.services import account_service

router = APIRouter(prefix="/users/me/favorites", tags=["Favorites"])


@router.get("", summary="List favorites")
async def list_favorites(user: CurrentUser, db: DbSession):
    """Spec #34. My Favorites — the same card shape discovery returns, so a
    restaurant renders identically wherever it is seen."""
    favorites = await account_service.list_favorites(db, user.id)
    return ok([f.model_dump() for f in favorites])


@router.post("/{restaurant_id}", summary="Toggle favorite")
async def toggle_favorite(restaurant_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Spec #34. One endpoint for both directions.

    The heart is a toggle, and the response carries the resulting state — two
    endpoints would let the client's idea of the state drift from ours.
    """
    result = await account_service.toggle_favorite(db, user.id, str(restaurant_id))
    await db.commit()
    return ok(result.model_dump())
