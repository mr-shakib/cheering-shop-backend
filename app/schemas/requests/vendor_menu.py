"""Menu building: categories, items, variants, add-ons, reordering."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.requests.base import Money


class VariantRequest(BaseModel):
    """A size/option that REPLACES the item's base price (decision D4).

    `id` is what makes an update a modification rather than a replacement. Send
    the id of an existing variant to edit it in place; omit it to create a new
    one. Any variant the payload does not mention is deleted — and deleting one
    cascades into every cart holding it, which is the correct outcome but not a
    reversible one.
    """

    id: str | None = Field(
        default=None, description="Omit to create; supply to update an existing variant"
    )
    name: str = Field(min_length=1, max_length=120)
    price: Money
    is_default: bool = Field(
        default=False,
        description="Preselected in the client. At most one per item; if none "
        "is marked, the first becomes the default.",
    )
    is_available: bool = True
    sort_order: int = Field(default=0, ge=0, le=9999)


class AddOnRequest(BaseModel):
    """An extra that ADDS to the resolved unit price (decision D4).

    Same `id` convention as `VariantRequest`.
    """

    id: str | None = Field(
        default=None, description="Omit to create; supply to update an existing add-on"
    )
    name: str = Field(min_length=1, max_length=120)
    price: Money
    is_available: bool = True
    sort_order: int = Field(default=0, ge=0, le=9999)


class MenuItemCreateRequest(BaseModel):
    """POST /vendor/menu/items"""

    name: str = Field(min_length=1, max_length=180)
    category_id: str
    description: str | None = Field(default=None, max_length=2000)
    base_price: Money
    is_available: bool = True
    is_veg: bool = False
    prep_time_mins: int | None = Field(default=None, ge=0, le=240)
    sort_order: int = Field(default=0, ge=0, le=9999)
    variants: list[VariantRequest] = Field(default_factory=list, max_length=50)
    add_ons: list[AddOnRequest] = Field(default_factory=list, max_length=50)
    image_url: str | None = Field(default=None, max_length=2048)


class MenuItemUpdateRequest(BaseModel):
    """PATCH /vendor/menu/items/{id} — [EXTENDED].

    PATCH, not PUT: an omitted field is left alone. That distinction is load
    bearing here, because every field is nullable and a PUT could not tell
    "leave the description" from "clear the description". Send an explicit
    `null` to clear.

    `variants` and `add_ons` are replace-sets when present — see
    `VariantRequest.id`. Omitting them entirely leaves both untouched, which is
    what a price-only edit wants.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=180)
    category_id: str | None = Field(
        default=None, description="Move the item to another category of the same restaurant"
    )
    description: str | None = Field(default=None, max_length=2000)
    base_price: Money | None = None
    image_url: str | None = Field(default=None, max_length=2048)
    is_available: bool | None = None
    is_veg: bool | None = None
    prep_time_mins: int | None = Field(default=None, ge=0, le=240)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    variants: list[VariantRequest] | None = Field(default=None, max_length=50)
    add_ons: list[AddOnRequest] | None = Field(default=None, max_length=50)


class MenuItemStatusRequest(BaseModel):
    """PATCH /vendor/menu/items/{id}/status"""

    is_available: bool


class MenuCategoryCreateRequest(BaseModel):
    """POST /vendor/menu/categories — [EXTENDED].

    The spec defines `GET /vendor/menu/categories` and `POST /vendor/menu/items`
    but nothing that creates a category, so a newly approved vendor had no way
    to build a menu at all: item creation requires a `category_id` that no
    endpoint could produce.
    """

    name: str = Field(min_length=1, max_length=120)
    sort_order: int = Field(default=0, ge=0, le=9999)
    is_active: bool = True


class MenuCategoryUpdateRequest(BaseModel):
    """PATCH /vendor/menu/categories/{id} — [EXTENDED]."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    is_active: bool | None = Field(
        default=None,
        description="Deactivating hides the whole category from customers "
        "without touching the items inside it",
    )


class ReorderEntry(BaseModel):
    id: str
    sort_order: int = Field(ge=0, le=9999)


class MenuReorderRequest(BaseModel):
    """PATCH /vendor/menu/reorder — [EXTENDED].

    Every sort_order column in the menu schema was previously unwritable. One
    endpoint for both levels, because reordering a menu is a single drag-and-drop
    gesture that should not become two half-applied requests.
    """

    categories: list[ReorderEntry] = Field(default_factory=list, max_length=200)
    items: list[ReorderEntry] = Field(default_factory=list, max_length=1000)
