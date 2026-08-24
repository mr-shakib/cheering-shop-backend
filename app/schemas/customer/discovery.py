"""Discovery, search and the public menu — spec #19–23."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


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


class MenuItemOut(BaseModel):
    """A dish. `variants` non-empty means the client MUST send a variant_id."""

    id: str
    category_id: str
    name: str
    description: str | None = None
    base_price: Decimal
    image_url: str | None = None
    is_available: bool
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
    """A cuisine filter chip on the home feed, with how many places match."""

    name: str
    restaurant_count: int
    image_url: str | None = None


class HomeFeed(BaseModel):
    """Spec #19. One request per app launch — anything the dashboard needs.

    `nearby` is empty rather than absent when coordinates are missing, so the
    client renders an empty carousel instead of branching on null.
    """

    cuisines: list[CuisineChip] = Field(default_factory=list)
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
