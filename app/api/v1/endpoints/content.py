"""Reels and app banners for the apps — [EXTENDED]. Public, like discovery."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession, OptionalUser, Paginated
from app.core.responses import ok, paginated
from app.services import banners, reels

router = APIRouter(tags=["Discovery"])


@router.get("/reels", summary="The Reels feed [EXTENDED]")
async def reel_feed(
    db: DbSession,
    viewer: OptionalUser,
    page: Paginated,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    restaurant_id: Annotated[
        uuid.UUID | None, Query(description="Only this restaurant's reels")
    ] = None,
):
    """**[EXTENDED]** — newest first. Each reel carries the restaurant card
    (name, rating, prep time, and distance and delivery fee when `lat`/`lng`
    are sent) that the overlay and the View button need."""
    rows, total = await reels.feed(
        db,
        limit=page.limit,
        offset=page.offset,
        lat=lat,
        lng=lng,
        restaurant_id=restaurant_id,
        user_id=viewer.id if viewer is not None else None,
    )
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/banners", summary="App banners [EXTENDED]")
async def live_banners(
    db: DbSession,
    placement: Annotated[str, Query(description="Where they show; HOME by default")] = "HOME",
):
    """**[EXTENDED]** — the banners showing now at `placement`, in display
    order. Render by `media_type`: IMAGE and GIF as images, LOTTIE with a
    Lottie player. The HOME ones also come with `GET /home/feed`."""
    return ok([b.model_dump() for b in await banners.live(db, placement)])
