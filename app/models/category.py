"""Platform-level browse categories — the "Burger", "Pizza", "Biryani" chips.

Two things are both called "category" in this codebase and they are not the
same thing:

* A **menu category** (`menu_categories`) is one restaurant's own section
  heading: "Chef's Specials", "Burgers", "Drinks". It belongs to that menu.
* A **category** here is the platform-wide bucket customers browse by. The
  home screen groups by this table, never by the free-text section name.

Menu categories point at one of these. A vendor creating a "Burger" section is
what makes their restaurant appear under the Burger chip: the section is
matched to a platform category by name (or created if nothing matches), and the
customer side counts restaurants through that link. Administrators curate the
result — image, pin order, hide, merge "Burgers" into "Burger".
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.models.menu import MenuCategory


class Category(Base, UUIDPrimaryKey, TimestampMixin):
    """[EXTENDED] A browse category. See the module docstring."""

    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Public identifier — what `GET /restaurants?category=` and the deep link
    # carry. Deliberately not recomputed when an admin renames the category,
    # for the same reason a restaurant slug survives a rebrand.
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    # NULL means "not pinned". Pinned categories (0, 1, 2 …) lead the customer
    # list in that order; everything else follows by how many restaurants
    # sell under it. A default of 0 would make every category "pinned first".
    sort_order: Mapped[int | None] = mapped_column(SmallInteger)
    # Other names this category answers to, stored as match keys (lower-cased,
    # single-spaced). A vendor section called "Hamburgers" resolves to Burger
    # instead of spawning a second chip. Merging one category into another
    # adds the loser's name here so the same spelling never comes back.
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    # Hidden from every customer surface, but still linkable — a vendor whose
    # section matched a hidden category keeps the link and simply does not
    # appear under it. A category a vendor's section name created starts
    # hidden: see `reviewed_at`.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # When an administrator last looked at this row. NULL means never, which
    # is the review queue: a category a vendor's section name brought into
    # existence, hidden until a person approves it.
    #
    # A separate column rather than inferring "hidden and unreviewed" from
    # `is_active`, because the two hidden states need different handling. One
    # is waiting for a decision; the other IS the decision, and must not keep
    # reappearing in the operator's queue.
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # passive_deletes: the database SET NULLs the sections itself, so deleting
    # a category must not make the ORM load the collection to do it by hand —
    # which, with lazy="raise", it could not.
    menu_categories: Mapped[list["MenuCategory"]] = relationship(
        back_populates="platform_category", lazy="raise", passive_deletes=True
    )

    # [EXTENDED] Migration 0009. NULL = not set at this level; a product's own
    # rate beats it, and it beats the restaurant's.
    commission_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    # The admin console's Restaurant / Store tabs.
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'RESTAURANT'")
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_categories_slug"),
        CheckConstraint("slug <> ''", name="ck_categories_slug"),
        CheckConstraint(
            "commission_rate IS NULL OR commission_rate BETWEEN 0 AND 1",
            name="ck_categories_commission",
        ),
        CheckConstraint("kind IN ('RESTAURANT', 'STORE')", name="ck_categories_kind"),
    )
