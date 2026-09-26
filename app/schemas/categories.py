"""Platform browse categories, as seen by every audience.

Customers get the chip (`schemas.customer.CategoryChip`), vendors see which
one their menu section lists under (`PlatformCategoryRef` on a menu category),
and administrators get the full row with usage counts (`CategoryAdminOut`).
The shared shapes live here rather than in one audience's package because the
same object crosses all three boundaries.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class PlatformCategoryRef(BaseModel):
    """The platform category a menu section lists under.

    Named `platform_category` wherever it appears next to a menu category, so
    it can never be mistaken for the section's own id.
    """

    id: str
    name: str
    slug: str = Field(description="Public id — what `GET /restaurants?category=` takes")
    image_url: str | None = None


class CategoryAdminOut(PlatformCategoryRef):
    """The administrator's view: everything on the row, plus who uses it."""

    sort_order: int | None = Field(
        default=None, description="Pinned position in the customer list; null = not pinned"
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Other spellings that resolve here, lower-cased",
    )
    is_active: bool
    reviewed_at: datetime | None = Field(
        default=None,
        description="When an administrator last decided about this category; "
        "null means never",
    )
    is_pending: bool = Field(
        description="Never reviewed — a vendor's section name created it and it "
        "is waiting for a decision. Hidden from customers until then."
    )
    restaurant_count: int = Field(
        description="Visible restaurants with a live section under this category — "
        "what the customer chip shows"
    )
    section_count: int = Field(
        description="Menu sections linked to it, across every restaurant, live or not"
    )
    product_count: int = Field(
        default=0, description="Undeleted products in those sections — the Total Product column"
    )
    commission_rate: float | None = Field(
        default=None,
        description="Commission for products under this category (0.15 == 15%); "
        "null = the restaurant's rate. A product's own rate beats it.",
    )
    kind: str = Field(default="RESTAURANT", description="RESTAURANT or STORE — the console tab")
    created_at: datetime
    updated_at: datetime
