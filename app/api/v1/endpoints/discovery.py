"""Location, Discovery & Menu — spec endpoints #19–23. All public."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import DbSession, OptionalUser, Paginated
from app.core.config import settings
from app.core.responses import ok, paginated
from app.services import account_service, discovery_service

router = APIRouter(tags=["Discovery"])

CategorySlug = Annotated[str, Path(min_length=1, max_length=100, description="The chip's `slug`")]


def _viewer_id(user) -> uuid.UUID | None:
    """The caller's id when signed in, else None — see deps.OptionalUser.

    Discovery is public, so this must never force authentication; it only
    enriches the response (filled hearts) when a token happens to be present.
    """
    return user.id if user is not None else None


@router.get("/home/feed", summary="App dashboard feed")
async def home_feed(
    db: DbSession,
    viewer: OptionalUser,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
):
    """Spec #19. Public. Aggregates categories, cuisines, offers and nearby
    restaurants.

    `categories` is the chip row — the platform categories vendors' menu
    sections list under, pinned ones first, at most twelve. `cuisines` is the
    older restaurant-level tag list and is kept for clients already rendering
    it. `nearby` comes back empty rather than absent when no coordinates are
    sent, so the client renders an empty carousel instead of branching on null.
    """
    feed = await discovery_service.home_feed(
        db, lat=lat, lng=lng, user_id=_viewer_id(viewer)
    )
    return ok(feed.model_dump())


@router.get("/restaurants", summary="Filtered restaurant list")
async def list_restaurants(
    db: DbSession,
    viewer: OptionalUser,
    page: Paginated,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius: Annotated[
        int, Query(ge=100, le=settings.MAX_SEARCH_RADIUS_METRES)
    ] = settings.DEFAULT_SEARCH_RADIUS_METRES,
    cuisine: str | None = None,
    category: Annotated[
        str | None, Query(max_length=100, description="A category `slug` from the chip row")
    ] = None,
    is_open: bool | None = None,
    sort: Annotated[str, Query(pattern="^(distance|rating|delivery_fee|prep_time)$")] = "distance",
    max_delivery_fee: Annotated[int | None, Query(ge=0)] = None,
    min_rating: Annotated[float | None, Query(ge=0, le=5)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    """Spec #20. Public — the Filter and Sort screen.

    Geospatial path uses ST_DWithin against the GiST index on
    `restaurants.location`. A radius filter in a WHERE clause built from
    ST_Distance would not be index-backed and would scan every row.

    A closed restaurant still appears (greyed by the client) unless `is_open`
    says otherwise: hiding it makes customers think it left the platform.
    """
    items, total = await discovery_service.list_restaurants(
        db,
        lat=lat,
        lng=lng,
        cuisine=cuisine,
        category=category,
        search=q,
        sort=sort,
        max_delivery_fee=max_delivery_fee,
        min_rating=min_rating,
        is_open=is_open,
        radius_m=radius,
        limit=page.limit,
        offset=page.offset,
        user_id=_viewer_id(viewer),
    )
    return paginated(
        [i.model_dump() for i in items], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/restaurants/{restaurant_id}", summary="Restaurant details")
async def get_restaurant(
    restaurant_id: uuid.UUID,
    db: DbSession,
    viewer: OptionalUser,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
):
    """Spec #21. Public. Carries live offers so the ribbon needs no second
    request."""
    detail = await discovery_service.restaurant_detail(
        db, str(restaurant_id), lat=lat, lng=lng, user_id=_viewer_id(viewer)
    )
    return ok(detail.model_dump())


@router.get("/restaurants/{restaurant_id}/menu", summary="Categorised menu")
async def get_restaurant_menu(restaurant_id: uuid.UUID, db: DbSession):
    """Spec #22. Public. Categories in sort_order, each with available items,
    variants and add-ons.

    Soft-deleted items and inactive categories are excluded here rather than
    left to the client: a dish the vendor removed must not be orderable because
    an app cached it.
    """
    menu = await discovery_service.restaurant_menu(db, str(restaurant_id))
    return ok([c.model_dump() for c in menu])


@router.get("/restaurants/{restaurant_id}/schedule", summary="Delivery slots")
async def get_schedule(restaurant_id: uuid.UUID, db: DbSession):
    """**[EXTENDED]** — the Schedule Order sheet.

    Slots are generated from the restaurant's business hours, not stored, so
    there is no table to drift out of sync with opening times. Slots inside the
    lead time come back marked unavailable rather than omitted — a picker that
    silently drops times looks broken.
    """
    options = await account_service.schedule_options(db, str(restaurant_id))
    return ok(options.model_dump())


@router.get("/categories", summary="Browse categories")
async def list_categories(db: DbSession):
    """**[EXTENDED]** — every category a customer can open, in chip order.

    Public. The full version of the home feed's `categories` (which stops at
    twelve). Only categories at least one visible restaurant sells under are
    returned, so nothing here opens onto an empty screen. This is also the
    picker a vendor app offers when a section should be filed somewhere
    other than where its name would land it.
    """
    chips = await discovery_service.list_categories(db)
    return ok([c.model_dump() for c in chips])


@router.get("/categories/{slug}", summary="One category")
async def get_category(slug: CategorySlug, db: DbSession):
    """**[EXTENDED]** — resolve a chip by slug, for deep links.

    An empty category comes back with `restaurant_count: 0` rather than 404:
    a shared link should open onto "nothing here yet", not a broken screen.
    Hidden categories are 404.
    """
    chip = await discovery_service.category_detail(db, slug)
    return ok(chip.model_dump())


@router.get("/categories/{slug}/items", summary="Dishes in a category")
async def list_category_items(
    slug: CategorySlug,
    db: DbSession,
    page: Paginated,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius: Annotated[
        int, Query(ge=100, le=settings.MAX_SEARCH_RADIUS_METRES)
    ] = settings.DEFAULT_SEARCH_RADIUS_METRES,
):
    """**[EXTENDED]** — "all burgers near me": dishes across every restaurant
    in the category, each carrying enough of its restaurant to render a card.

    Send `lat`/`lng` to restrict to `radius` metres and sort nearest first;
    without coordinates every visible restaurant's dishes qualify. The
    restaurants themselves are `GET /restaurants?category={slug}`.
    """
    items, total = await discovery_service.category_items(
        db, slug, lat=lat, lng=lng, radius_m=radius, limit=page.limit, offset=page.offset
    )
    return paginated(
        [i.model_dump() for i in items], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/search", summary="Global search")
async def search(
    db: DbSession,
    viewer: OptionalUser,
    page: Paginated,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
):
    """Spec #23. Public. Restaurants, dishes and categories in one response.

    A dish hit carries its restaurant's name, because "Chicken Biryani ৳320" is
    not actionable without knowing who sells it. `categories` offers the chip
    when the query looks like one — typing "bur" should surface Burger.
    """
    results = await discovery_service.search(
        db, q, lat=lat, lng=lng, limit=page.limit, user_id=_viewer_id(viewer)
    )
    return ok(results.model_dump())
