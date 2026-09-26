"""Menu tree: categories, items, variants, add-ons."""

from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.categories import PlatformCategoryRef


class VariantOut(BaseModel):
    """Decision D4: `price` REPLACES the item's base price — it is absolute."""

    id: str
    name: str
    price: Decimal
    is_default: bool
    is_available: bool
    sort_order: int


class AddOnOut(BaseModel):
    """Decision D4: `price` ADDS to the resolved unit price."""

    id: str
    name: str
    price: Decimal
    is_available: bool
    sort_order: int
    max_quantity: int = Field(default=1, description="Most a customer may pick per unit")


class MenuItemOut(BaseModel):
    id: str
    restaurant_id: str
    category_id: str
    name: str
    description: str | None = None
    base_price: Decimal = Field(
        description="Display price. When `variants` is non-empty this is a "
        '"from" price only — the variant price is what the customer pays.'
    )
    image_url: str | None = None
    is_available: bool
    is_hidden: bool = Field(
        default=False,
        description="Hidden from customers by an administrator. Not yours to change — "
        "contact support",
    )
    is_featured: bool = Field(default=False, description="Promoted by the platform")
    commission_rate: float | None = Field(
        default=None,
        description="This dish's own commission, set by the platform; null means "
        "the category's or your restaurant's rate applies",
    )
    is_veg: bool
    prep_time_mins: int | None = None
    sort_order: int
    variants: list[VariantOut] = Field(default_factory=list)
    add_ons: list[AddOnOut] = Field(default_factory=list)


class MenuCategoryOut(BaseModel):
    id: str
    restaurant_id: str
    name: str
    sort_order: int
    is_active: bool
    item_count: int = Field(description="Live items in this category, excluding deleted ones")
    platform_category: PlatformCategoryRef | None = Field(
        default=None,
        description="The browse category customers find this section under; "
        "null when the section is unlinked",
    )


class MenuCategoryWithItems(MenuCategoryOut):
    """A category and its items — the shape `GET /vendor/menu` returns."""

    items: list[MenuItemOut] = Field(default_factory=list)


class VendorMenu(BaseModel):
    """The vendor's own menu, unfiltered.

    Unlike the public `GET /restaurants/{id}/menu`, this includes inactive
    categories and sold-out items: a vendor cannot switch an item back on if
    switching it off made it disappear from their own screen.
    """

    restaurant_id: str
    categories: list[MenuCategoryWithItems] = Field(default_factory=list)
