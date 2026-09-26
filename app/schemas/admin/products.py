"""The admin Product screens: the platform-wide list and the product drawer."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.categories import PlatformCategoryRef
from app.schemas.vendor import AddOnOut, VariantOut


class ProductCommission(BaseModel):
    """Every level a rate can be set at, and which one this product is
    actually charged at: the most specific one that is set."""

    rate: float = Field(description="The rate orders charge, as a fraction (0.15 == 15%)")
    source: str = Field(description="PRODUCT, CATEGORY or RESTAURANT — where `rate` came from")
    product_rate: float | None = None
    category_rate: float | None = None
    restaurant_rate: float


class AdminProductRow(BaseModel):
    id: str
    name: str
    image_url: str | None = None
    restaurant_id: str
    restaurant_name: str
    business_type: str | None = Field(
        default=None, description="RESTAURANT, GROCERY or PHARMACY — the Type badge"
    )
    section_id: str = Field(description="The vendor's menu section holding it")
    section_name: str
    platform_category: PlatformCategoryRef | None = Field(
        default=None, description="The browse category that section lists under"
    )
    base_price: Decimal
    status: str = Field(
        description="HIDDEN (by an admin), UNAVAILABLE (sold out, the vendor's switch) or ACTIVE"
    )
    is_available: bool
    is_hidden: bool
    is_featured: bool
    commission: ProductCommission
    created_at: datetime


class AdminProductDetail(AdminProductRow):
    """The product drawer."""

    description: str | None = None
    is_veg: bool
    prep_time_mins: int | None = None
    variants: list[VariantOut]
    add_ons: list[AddOnOut]
    commission_amount: Decimal = Field(description="Commission on base_price at `commission.rate`")
    net_amount: Decimal = Field(description="base_price − commission_amount: what the vendor keeps")
