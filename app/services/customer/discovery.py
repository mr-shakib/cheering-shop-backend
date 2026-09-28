"""Discovery, search and the public menu — spec #19–23. All public.

**Distance ranking happens in PostGIS, not in Python.** Every restaurant row is
a candidate, so filtering and ordering must run in the database where the
`location` GiST index can be used; pulling rows into the process to sort them
is the difference between an indexed lookup and a full scan. Checkout does the
opposite — see `services/pricing.haversine_km` — because there it is two points
already in memory.

Everything here reads. Nothing in this module writes, which is why it can be
served to anonymous callers without a permission check beyond "is the
restaurant visible at all".
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Float, and_, cast, false, func, null, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.money import to_major, to_minor
from app.models.category import Category
from app.models.enums import RestaurantStatus
from app.models.menu import MenuCategory, MenuItem
from app.models.promo import PromoCode
from app.models.restaurant import Favorite, Restaurant
from app.schemas.customer import (
    AddOnOut,
    CategoryChip,
    CategoryDish,
    CuisineChip,
    HomeFeed,
    MenuCategoryOut,
    MenuItemOut,
    PromotionBanner,
    RestaurantCard,
    RestaurantDetail,
    SearchItemHit,
    SearchResults,
    VariantOut,
)
from app.services import banners as banner_service
from app.services import category_service, platform_settings
from app.services.pricing import (
    DeliveryFees,
    delivery_fee_minor,
    delivery_reach_km,
    haversine_km,
)

# A restaurant is only discoverable when the vendor is verified AND has not
# deactivated the storefront. `status` (OPEN/CLOSED) is separate and does NOT
# hide the listing: a closed kitchen still appears, greyed, because hiding it
# makes customers think the restaurant has left the platform. Defined once, in
# category_service, so the chip counts and this module can never disagree
# about who is visible.
_VISIBLE = category_service.VISIBLE_RESTAURANT


def _distance_expr(lat: float | None, lng: float | None):
    """Metres from the caller to each restaurant, or NULL when unlocated.

    `ST_Distance` on `geography` returns metres, so no projection maths is
    needed. Returning NULL rather than 0 for an unlocated caller matters: 0
    would sort every restaurant to the top of a "nearest first" list.
    """
    if lat is None or lng is None:
        return cast(null(), Float)
    origin = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
    return func.ST_Distance(Restaurant.location, func.cast(origin, Restaurant.location.type))


def _to_card(
    row, fees: DeliveryFees, favorite_ids: set[uuid.UUID] | None = None
) -> RestaurantCard:
    restaurant, distance_m = row
    distance_km = distance_m / 1000 if distance_m is not None else 0.0
    return RestaurantCard(
        id=str(restaurant.id),
        name=restaurant.name,
        slug=restaurant.slug,
        cuisine_types=list(restaurant.cuisine_types or []),
        logo_url=restaurant.logo_url,
        cover_image_url=restaurant.cover_image_url,
        rating_avg=float(restaurant.rating_avg or 0),
        rating_count=restaurant.rating_count,
        avg_prep_time_mins=restaurant.avg_prep_time_mins,
        # The fee for this distance on the tariff checkout charges, so a
        # restaurant 6 km away no longer advertises the 1 km price. Unlocated,
        # it is the fee at zero distance — the least any address pays. An
        # item_total of 0 leaves the free-delivery threshold out: there is no
        # cart here, and checkout still applies it.
        delivery_fee=to_major(delivery_fee_minor(distance_km, 0, fees)),
        min_order_amount=to_major(restaurant.min_order_amount),
        is_open=str(restaurant.status) == RestaurantStatus.OPEN,
        distance_km=round(distance_m / 1000, 2) if distance_m is not None else None,
        is_favorite=bool(favorite_ids and restaurant.id in favorite_ids),
    )


async def _favorite_ids(db: AsyncSession, user_id: uuid.UUID | None) -> set[uuid.UUID]:
    """One query for the whole page, rather than one per card."""
    if user_id is None:
        return set()
    rows = await db.scalars(select(Favorite.restaurant_id).where(Favorite.user_id == user_id))
    return set(rows.all())


async def list_restaurants(
    db: AsyncSession,
    *,
    lat: float | None = None,
    lng: float | None = None,
    cuisine: str | None = None,
    category: str | None = None,
    search: str | None = None,
    sort: str = "distance",
    max_delivery_fee: int | None = None,
    min_rating: float | None = None,
    is_open: bool | None = None,
    radius_m: int | None = None,
    limit: int = 20,
    offset: int = 0,
    user_id: uuid.UUID | None = None,
) -> tuple[list[RestaurantCard], int]:
    """Spec #20 — the Filter and Sort screen, in one query.

    Radius is applied with `ST_DWithin`, which is index-backed; `ST_Distance`
    in a WHERE clause is not, and would scan every row before discarding most
    of them.
    """
    distance = _distance_expr(lat, lng)
    fees = await platform_settings.delivery_fees(db)
    conditions = [_VISIBLE]

    if lat is not None and lng is not None:
        radius = min(radius_m or settings.DEFAULT_SEARCH_RADIUS_METRES,
                     settings.MAX_SEARCH_RADIUS_METRES)
        origin = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
        conditions.append(
            func.ST_DWithin(
                Restaurant.location, func.cast(origin, Restaurant.location.type), radius
            )
        )
    if cuisine:
        # The column is a text[]; `any` is an index-friendly containment test.
        # `contains` maps to the array @> operator, which the GIN index on
        # cuisine_types can serve.
        conditions.append(Restaurant.cuisine_types.contains([cuisine]))
    if category:
        # The chip's slug. Same predicate the chip's count was built from, so
        # the list is exactly as long as the number the customer just tapped.
        conditions.append(category_service.sells_under(category))
    if search:
        conditions.append(Restaurant.name.ilike(f"%{search}%"))
    if max_delivery_fee is not None:
        # The fee grows with distance, so a fee ceiling is a distance ceiling.
        # Unlocated, every card shows the zero-distance fee, so the filter is
        # all-or-nothing against that.
        reach_km = delivery_reach_km(to_minor(max_delivery_fee), fees)
        if reach_km is not None and reach_km < 0:
            conditions.append(false())
        elif reach_km is not None and lat is not None and lng is not None:
            conditions.append(distance <= reach_km * 1000)
    if min_rating is not None:
        conditions.append(Restaurant.rating_avg >= min_rating)
    if is_open is not None:
        wanted = RestaurantStatus.OPEN if is_open else RestaurantStatus.CLOSED
        conditions.append(Restaurant.status == wanted.value)

    where = and_(*conditions)
    total = await db.scalar(select(func.count()).select_from(Restaurant).where(where)) or 0

    order_by = {
        "rating": (Restaurant.rating_avg.desc(), Restaurant.rating_count.desc()),
        # The fee only rises with distance, so cheapest delivery first is
        # nearest first. Unlocated, every fee is the same and rating decides.
        "delivery_fee": (distance.asc().nulls_last(), Restaurant.rating_avg.desc()),
        "prep_time": (Restaurant.avg_prep_time_mins.asc(),),
        # NULLS LAST so an unlocated caller does not get a list ordered by
        # nothing in particular ahead of the rating tiebreak.
        "distance": (distance.asc().nulls_last(), Restaurant.rating_avg.desc()),
    }.get(sort, (distance.asc().nulls_last(), Restaurant.rating_avg.desc()))

    rows = await db.execute(
        select(Restaurant, distance).where(where).order_by(*order_by).limit(limit).offset(offset)
    )
    favorites = await _favorite_ids(db, user_id)
    return [_to_card(r, fees, favorites) for r in rows.all()], total


async def home_feed(
    db: AsyncSession,
    *,
    lat: float | None = None,
    lng: float | None = None,
    user_id: uuid.UUID | None = None,
) -> HomeFeed:
    """Spec #19. One request per app launch.

    Three carousels are three queries rather than one clever one: they have
    different orderings and different limits, and a UNION that produced all
    three would be slower and far harder to change than three indexed reads.
    """
    favorites = await _favorite_ids(db, user_id)
    fees = await platform_settings.delivery_fees(db)
    distance = _distance_expr(lat, lng)

    # unnest() must be expanded in a subquery before it can be grouped:
    # PostgreSQL refuses GROUP BY on a set-returning function's output alias in
    # the same SELECT that produces it.
    exploded = (
        select(func.unnest(Restaurant.cuisine_types).label("name"))
        .where(_VISIBLE)
        .subquery()
    )
    cuisine_rows = await db.execute(
        select(exploded.c.name, func.count())
        .group_by(exploded.c.name)
        .order_by(func.count().desc())
        .limit(12)
    )
    cuisines = [CuisineChip(name=n, restaurant_count=c) for n, c in cuisine_rows.all()]
    categories = await list_categories(db, limit=12)

    async def _cards(order_by, limit: int, extra=None) -> list[RestaurantCard]:
        where = _VISIBLE if extra is None else and_(_VISIBLE, extra)
        rows = await db.execute(
            select(Restaurant, distance).where(where).order_by(*order_by).limit(limit)
        )
        return [_to_card(r, fees, favorites) for r in rows.all()]

    nearby: list[RestaurantCard] = []
    if lat is not None and lng is not None:
        origin = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
        nearby = await _cards(
            (distance.asc(),),
            10,
            func.ST_DWithin(
                Restaurant.location,
                func.cast(origin, Restaurant.location.type),
                settings.DEFAULT_SEARCH_RADIUS_METRES,
            ),
        )

    # "Promoted" is currently "has a live offer" — an honest proxy until paid
    # placement exists. Sorting by rating within that keeps it from becoming a
    # dumping ground for whoever launched a promo most recently.
    now = func.now()
    promoted_ids = select(PromoCode.restaurant_id).where(
        PromoCode.is_active.is_(True),
        PromoCode.restaurant_id.is_not(None),
        PromoCode.valid_from <= now,
        PromoCode.valid_until >= now,
    )
    promoted = await _cards(
        (Restaurant.rating_avg.desc(),), 10, Restaurant.id.in_(promoted_ids)
    )
    top_rated = await _cards(
        (Restaurant.rating_avg.desc(), Restaurant.rating_count.desc()),
        10,
        Restaurant.rating_count > 0,
    )
    return HomeFeed(
        banners=await banner_service.live(db, "HOME"),
        cuisines=cuisines,
        categories=categories,
        promoted=promoted,
        nearby=nearby,
        top_rated=top_rated,
    )


# ---------------------------------------------------------------------------
# Browse categories — the chip row and what a tap opens
# ---------------------------------------------------------------------------


def _to_chip(category: Category, restaurant_count: int) -> CategoryChip:
    return CategoryChip(
        id=str(category.id),
        name=category.name,
        slug=category.slug,
        image_url=category.image_url,
        restaurant_count=int(restaurant_count),
    )


async def list_categories(
    db: AsyncSession, *, limit: int | None = None, query: str | None = None
) -> list[CategoryChip]:
    """[EXTENDED] Categories a customer can actually open.

    Only active categories with at least one visible restaurant selling under
    them — the inner join against `restaurant_counts` is the filter. Pinned
    first (an operator's "Burger, Pizza, Biryani" order), then by how many
    restaurants each one holds, so an unpinned tail sorts itself by demand.
    """
    counts = category_service.restaurant_counts()
    stmt = (
        select(Category, counts.c.restaurant_count)
        .join(counts, counts.c.category_id == Category.id)
        .where(Category.is_active.is_(True))
        .order_by(
            Category.sort_order.asc().nulls_last(),
            counts.c.restaurant_count.desc(),
            Category.name,
        )
    )
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            or_(
                Category.name.ilike(pattern),
                func.array_to_string(Category.aliases, " ").ilike(pattern),
            )
        )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = await db.execute(stmt)
    return [_to_chip(c, n) for c, n in rows.all()]


async def _active_category(db: AsyncSession, slug: str) -> Category:
    """By slug, or by a slug it absorbed in a merge — an exact slug wins."""
    category = await db.scalar(
        select(Category)
        .where(category_service.by_slug(slug), Category.is_active.is_(True))
        .order_by((Category.slug == slug).desc())
        .limit(1)
    )
    if category is None:
        raise NotFoundError("Category not found")
    return category


async def category_detail(db: AsyncSession, slug: str) -> CategoryChip:
    """[EXTENDED] One chip by slug — what a deep link resolves.

    Unlike the list, an empty category is returned here (with a count of 0)
    rather than hidden: a shared link should open onto "nothing here yet",
    not a 404 that reads as a broken app.
    """
    category = await _active_category(db, slug)
    counts = category_service.restaurant_counts()
    count = await db.scalar(
        select(counts.c.restaurant_count).where(counts.c.category_id == category.id)
    )
    return _to_chip(category, count or 0)


def _to_dish(item: MenuItem, restaurant: Restaurant, distance_m: float | None) -> CategoryDish:
    return CategoryDish(
        id=str(item.id),
        name=item.name,
        description=item.description,
        image_url=item.image_url,
        base_price=to_major(item.base_price),
        is_veg=item.is_veg,
        is_available=item.is_available,
        restaurant_id=str(restaurant.id),
        restaurant_name=restaurant.name,
        restaurant_is_open=str(restaurant.status) == RestaurantStatus.OPEN,
        restaurant_rating_avg=float(restaurant.rating_avg or 0),
        distance_km=round(distance_m / 1000, 2) if distance_m is not None else None,
    )


async def category_items(
    db: AsyncSession,
    slug: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[CategoryDish], int]:
    """[EXTENDED] "All burgers near me" — dishes across every restaurant.

    A dish is in a category through its menu section's link, so a vendor who
    files "Beef Burger" under a "Burgers" section has put it here without
    tagging the item. Orderable first, then open kitchens, then nearest, then
    best rated: a sold-out dish from a closed restaurant is still an honest
    answer, but it goes at the bottom.
    """
    category = await _active_category(db, slug)
    distance = _distance_expr(lat, lng)
    conditions = [
        _VISIBLE,
        MenuCategory.category_id == category.id,
        MenuCategory.is_active.is_(True),
        MenuItem.deleted_at.is_(None),
        MenuItem.is_hidden.is_(False),
    ]
    if lat is not None and lng is not None:
        radius = min(
            radius_m or settings.DEFAULT_SEARCH_RADIUS_METRES, settings.MAX_SEARCH_RADIUS_METRES
        )
        origin = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
        conditions.append(
            func.ST_DWithin(
                Restaurant.location, func.cast(origin, Restaurant.location.type), radius
            )
        )

    def _from(stmt):
        return (
            stmt.select_from(MenuItem)
            .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
            .join(Restaurant, Restaurant.id == MenuItem.restaurant_id)
            .where(*conditions)
        )

    total = await db.scalar(_from(select(func.count()))) or 0
    rows = await db.execute(
        _from(select(MenuItem, Restaurant, distance))
        .order_by(
            MenuItem.is_available.desc(),
            (Restaurant.status == RestaurantStatus.OPEN.value).desc(),
            distance.asc().nulls_last(),
            Restaurant.rating_avg.desc(),
            MenuItem.name,
        )
        .limit(limit)
        .offset(offset)
    )
    return [_to_dish(item, restaurant, d) for item, restaurant, d in rows.all()], total


async def _load_visible(db: AsyncSession, restaurant_id: str) -> Restaurant:
    try:
        rid = uuid.UUID(restaurant_id)
    except ValueError as exc:
        raise NotFoundError("Restaurant not found") from exc
    restaurant = await db.scalar(select(Restaurant).where(Restaurant.id == rid, _VISIBLE))
    if restaurant is None:
        raise NotFoundError("Restaurant not found")
    return restaurant


async def restaurant_detail(
    db: AsyncSession,
    restaurant_id: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
    user_id: uuid.UUID | None = None,
) -> RestaurantDetail:
    """Spec #21. Includes live offers so the ribbon needs no second request."""
    restaurant = await _load_visible(db, restaurant_id)
    distance_m = None
    if lat is not None and lng is not None:
        distance_m = haversine_km(lat, lng, restaurant.latitude, restaurant.longitude) * 1000

    favorites = await _favorite_ids(db, user_id)
    fees = await platform_settings.delivery_fees(db)
    card = _to_card((restaurant, distance_m), fees, favorites)

    now = func.now()
    promos = await db.scalars(
        select(PromoCode).where(
            PromoCode.restaurant_id == restaurant.id,
            PromoCode.is_active.is_(True),
            PromoCode.valid_from <= now,
            PromoCode.valid_until >= now,
        )
    )
    banners = [
        PromotionBanner(
            code=p.code,
            title=p.description or p.code,
            discount_type=str(p.discount_type),
            discount_value=to_major(p.discount_value)
            if str(p.discount_type) == "FIXED"
            else Decimal(p.discount_value) / 100,
            min_order_amount=to_major(p.min_order_amount),
            max_discount=to_major(p.max_discount) if p.max_discount else None,
            valid_until=p.valid_until,
        )
        for p in promos.all()
    ]
    return RestaurantDetail(
        **card.model_dump(),
        description=restaurant.description,
        phone=restaurant.phone,
        address_line=restaurant.address_line,
        latitude=restaurant.latitude,
        longitude=restaurant.longitude,
        business_hours=restaurant.business_hours,
        promotions=banners,
    )


async def restaurant_menu(db: AsyncSession, restaurant_id: str) -> list[MenuCategoryOut]:
    """Spec #22. The categorised menu.

    Soft-deleted and inactive rows are excluded here rather than filtered by
    the client: a dish the vendor removed must not be orderable because an app
    cached it.
    """
    restaurant = await _load_visible(db, restaurant_id)
    rows = await db.scalars(
        select(MenuCategory)
        .where(MenuCategory.restaurant_id == restaurant.id, MenuCategory.is_active.is_(True))
        .order_by(MenuCategory.sort_order, MenuCategory.name)
    )
    categories = list(rows.all())
    if not categories:
        return []

    items = await db.scalars(
        select(MenuItem)
        .where(
            MenuItem.category_id.in_([c.id for c in categories]),
            MenuItem.deleted_at.is_(None),
            MenuItem.is_hidden.is_(False),
        )
        .order_by(MenuItem.sort_order, MenuItem.name)
        .options(selectinload(MenuItem.variants), selectinload(MenuItem.add_ons))
    )
    by_category: dict[uuid.UUID, list[MenuItemOut]] = {}
    for item in items.all():
        by_category.setdefault(item.category_id, []).append(_to_item(item))

    return [
        MenuCategoryOut(
            id=str(c.id),
            name=c.name,
            sort_order=c.sort_order,
            items=by_category.get(c.id, []),
        )
        for c in categories
    ]


def _to_item(item: MenuItem) -> MenuItemOut:
    return MenuItemOut(
        id=str(item.id),
        category_id=str(item.category_id),
        name=item.name,
        description=item.description,
        base_price=to_major(item.base_price),
        image_url=item.image_url,
        is_available=item.is_available,
        is_featured=item.is_featured,
        is_veg=item.is_veg,
        prep_time_mins=item.prep_time_mins,
        variants=sorted(
            (
                VariantOut(
                    id=str(v.id),
                    name=v.name,
                    price=to_major(v.price),
                    is_default=v.is_default,
                    is_available=v.is_available,
                )
                for v in item.variants
            ),
            key=lambda v: (not v.is_default, v.name),
        ),
        add_ons=[
            AddOnOut(
                id=str(a.id),
                name=a.name,
                price=to_major(a.price),
                is_available=a.is_available,
                max_quantity=a.max_quantity,
            )
            for a in sorted(item.add_ons, key=lambda a: (a.sort_order, a.name))
        ],
    )


async def search(
    db: AsyncSession,
    query: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
    limit: int = 20,
    user_id: uuid.UUID | None = None,
) -> SearchResults:
    """Spec #23. Restaurants and dishes together.

    A dish hit carries its restaurant's name because "Chicken Biryani ৳320" is
    not actionable without knowing who sells it — the Search results screen
    renders exactly that pairing.
    """
    query = query.strip()
    if not query:
        return SearchResults()

    restaurants, _ = await list_restaurants(
        db, lat=lat, lng=lng, search=query, limit=limit, user_id=user_id,
        radius_m=settings.MAX_SEARCH_RADIUS_METRES,
    )

    pattern = f"%{query}%"
    rows = await db.execute(
        select(MenuItem, Restaurant.name)
        .join(Restaurant, Restaurant.id == MenuItem.restaurant_id)
        .where(
            _VISIBLE,
            MenuItem.deleted_at.is_(None),
            MenuItem.is_hidden.is_(False),
            or_(MenuItem.name.ilike(pattern), MenuItem.description.ilike(pattern)),
        )
        # Available first: an unavailable dish is still a useful search hit
        # (it tells you the restaurant sells it) but must not lead the list.
        .order_by(MenuItem.is_available.desc(), MenuItem.name)
        .limit(limit)
    )
    items = [
        SearchItemHit(
            id=str(item.id),
            name=item.name,
            image_url=item.image_url,
            base_price=to_major(item.base_price),
            restaurant_id=str(item.restaurant_id),
            restaurant_name=restaurant_name,
            is_available=item.is_available,
        )
        for item, restaurant_name in rows.all()
    ]
    categories = await list_categories(db, limit=5, query=query)
    return SearchResults(restaurants=restaurants, items=items, categories=categories)


__all__ = [
    "category_detail",
    "category_items",
    "home_feed",
    "list_categories",
    "list_restaurants",
    "restaurant_detail",
    "restaurant_menu",
    "search",
]
