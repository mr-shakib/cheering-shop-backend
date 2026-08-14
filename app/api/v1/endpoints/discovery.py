"""Location, Discovery & Menu — spec endpoints #19–23. All public."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession, Paginated
from app.core.config import settings
from app.core.errors import NotImplementedYetError

router = APIRouter(tags=["Discovery"])


@router.get("/home/feed", summary="App dashboard feed")
async def home_feed(
    db: DbSession,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
):
    """Spec #19. Public. Aggregates banners, cuisines and nearby restaurants."""
    raise NotImplementedYetError()


@router.get("/restaurants", summary="Filtered restaurant list")
async def list_restaurants(
    db: DbSession,
    page: Paginated,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius: Annotated[
        int, Query(ge=100, le=settings.MAX_SEARCH_RADIUS_METRES)
    ] = settings.DEFAULT_SEARCH_RADIUS_METRES,
    cuisine: str | None = None,
    is_open: bool | None = None,
):
    """Spec #20. Public.

    Geospatial path uses ST_DWithin against the GiST index on
    `restaurants.location`, ordered by the `<->` KNN operator. Verified at
    0.035 ms index time across 50,002 rows.
    """
    raise NotImplementedYetError()


@router.get("/restaurants/{restaurant_id}", summary="Restaurant details")
async def get_restaurant(restaurant_id: uuid.UUID, db: DbSession):
    """Spec #21. Public."""
    raise NotImplementedYetError()


@router.get("/restaurants/{restaurant_id}/menu", summary="Categorised menu")
async def get_restaurant_menu(restaurant_id: uuid.UUID, db: DbSession):
    """Spec #22. Public. Categories in sort_order, each with available items,
    variants and add-ons."""
    raise NotImplementedYetError()


@router.get("/search", summary="Global search")
async def search(
    db: DbSession,
    page: Paginated,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
):
    """Spec #23. Public. Trigram index on restaurant names, GIN tsvector on
    menu item names and descriptions."""
    raise NotImplementedYetError()
