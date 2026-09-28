"""Discovery, search and the public menu — spec #19–23."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.content import BannerOut


class RestaurantCard(BaseModel):
    """One row in a list: home feed, search results, favorites, category list.

    Deliberately flat and small. The listing screens render ~20 of these over
    mobile data, and the details screen re-fetches anyway.
    """

    id: str
    name: str
    slug: str
    cuisine_types: list[str] = Field(default_factory=list)
    logo_url: str | None = None
    cover_image_url: str | None = None
    rating_avg: float
    rating_count: int
    avg_prep_time_mins: int
    delivery_fee: Decimal
    min_order_amount: Decimal
    is_open: bool
    # Null when the caller sent no coordinates — the client shows "—" rather
    # than a fabricated distance.
    distance_km: float | None = None
    is_favorite: bool = False


class VariantOut(BaseModel):
    id: str
    name: str
    price: Decimal
    is_default: bool
    is_available: bool


class AddOnOut(BaseModel):
    id: str
    name: str
    price: Decimal
    is_available: bool
    max_quantity: int = Field(
        default=1,
        description="Most a customer may pick per unit — 1 means a checkbox, more a stepper",
    )


class MenuItemOut(BaseModel):
    """A dish. `variants` non-empty means the client MUST send a variant_id."""

    id: str
    category_id: str
    name: str
    description: str | None = None
    base_price: Decimal
    image_url: str | None = None
    is_available: bool
    is_featured: bool = Field(default=False, description="Promoted by the platform")
    is_veg: bool
    prep_time_mins: int | None = None
    variants: list[VariantOut] = Field(default_factory=list)
    add_ons: list[AddOnOut] = Field(default_factory=list)


class MenuCategoryOut(BaseModel):
    id: str
    name: str
    sort_order: int
    items: list[MenuItemOut] = Field(default_factory=list)


class RestaurantDetail(RestaurantCard):
    """The Restaurant Details screen. Extends the card rather than replacing it
    so the client can reuse one model when it navigates from a list."""

    description: str | None = None
    phone: str | None = None
    address_line: str | None = None
    latitude: float
    longitude: float
    business_hours: dict | None = None
    # Live offers, so the "20% off on orders over ৳500" ribbon needs no
    # second request.
    promotions: list["PromotionBanner"] = Field(default_factory=list)


class PromotionBanner(BaseModel):
    """The offer ribbon. Mirrors what the vendor launched, minus the budget
    internals — a customer has no business seeing spend against cap."""

    code: str
    title: str
    discount_type: str
    discount_value: Decimal
    min_order_amount: Decimal
    max_discount: Decimal | None = None
    valid_until: datetime | None = None


class CuisineChip(BaseModel):
    """A cuisine filter chip on the home feed, with how many places match.

    Cuisines are restaurant-level tags ("Bengali", "Chinese") and predate the
    platform categories below. Kept for clients already rendering them; the
    chip row on the home screen should now use `categories`.
    """

    name: str
    restaurant_count: int
    image_url: str | None = None


class CategoryChip(BaseModel):
    """A browse category — the "Burger" chip.

    `slug` is what to send back: `GET /restaurants?category={slug}` for the
    restaurants, `GET /categories/{slug}/items` for the dishes. Only categories
    at least one visible restaurant sells under are ever returned, so a chip
    never opens onto an empty screen.
    """

    id: str
    name: str
    slug: str
    image_url: str | None = None
    restaurant_count: int


class CategoryDish(BaseModel):
    """One dish in a category listing — "all burgers near me".

    Carries enough of the restaurant to render the card without a second
    request, and `distance_km` when the caller sent coordinates.
    """

    id: str
    name: str
    description: str | None = None
    image_url: str | None = None
    base_price: Decimal
    is_veg: bool
    is_available: bool
    restaurant_id: str
    restaurant_name: str
    restaurant_is_open: bool
    restaurant_rating_avg: float
    distance_km: float | None = None


class HomeFeed(BaseModel):
    """Spec #19. One request per app launch — anything the dashboard needs.

    `nearby` is empty rather than absent when coordinates are missing, so the
    client renders an empty carousel instead of branching on null.
    """

    # [EXTENDED] The admin-managed banners for the HOME placement, in order.
    banners: list[BannerOut] = Field(default_factory=list)
    cuisines: list[CuisineChip] = Field(default_factory=list)
    # The chip row. Pinned categories first, then by how many restaurants sell
    # under each; at most twelve — `GET /categories` has the full list.
    categories: list[CategoryChip] = Field(default_factory=list)
    promoted: list[RestaurantCard] = Field(default_factory=list)
    nearby: list[RestaurantCard] = Field(default_factory=list)
    top_rated: list[RestaurantCard] = Field(default_factory=list)


class SearchResults(BaseModel):
    """Spec #23. Restaurants and dishes in one response.

    Dishes carry their restaurant's id and name because a search hit on
    "biryani" is useless without knowing who sells it.
    """

    restaurants: list[RestaurantCard] = Field(default_factory=list)
    items: list["SearchItemHit"] = Field(default_factory=list)
    # Typing "bur" should offer the Burger chip, not only burger-named dishes.
    categories: list[CategoryChip] = Field(default_factory=list)


class SearchItemHit(BaseModel):
    id: str
    name: str
    image_url: str | None = None
    base_price: Decimal
    restaurant_id: str
    restaurant_name: str
    is_available: bool


RestaurantDetail.model_rebuild()
SearchResults.model_rebuild()


class ReelDish(BaseModel):
    id: str
    name: str
    price: Decimal


class ReelOut(BaseModel):
    """[EXTENDED] One reel in the customer feed. `restaurant` is the same card
    the lists show, so the overlay (name, rating, time, distance) and the View
    button need no second request."""

    id: str
    video_url: str
    thumbnail_url: str | None = None
    caption: str | None = None
    duration_seconds: int | None = None
    restaurant: RestaurantCard
    menu_item: ReelDish | None = None
    created_at: datetime
