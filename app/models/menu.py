"""Menu catalog: categories, items, variants, add-ons."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, TimestampMixin, UUIDPrimaryKey


class MenuCategory(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "menu_categories"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    restaurant: Mapped["Restaurant"] = relationship(back_populates="categories", lazy="raise")  # noqa: F821
    items: Mapped[list["MenuItem"]] = relationship(back_populates="category", lazy="raise")

    __table_args__ = (
        UniqueConstraint("restaurant_id", "name", name="uq_menu_categories_name"),
        # FK target letting menu_items carry a *verified* restaurant_id.
        UniqueConstraint("id", "restaurant_id", name="uq_menu_categories_id_restaurant"),
        Index("ix_menu_categories_restaurant", "restaurant_id", "sort_order"),
    )


class MenuItem(Base, UUIDPrimaryKey, TimestampMixin):
    """restaurant_id is denormalized on purpose.

    It anchors the composite-FK chain that makes the single-restaurant cart rule
    structural rather than advisory, and lets the cart check the rule without a
    join. The composite FK to menu_categories makes the denormalized value
    impossible to falsify.
    """

    __tablename__ = "menu_items"

    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Decision D4: when this item has variants, base_price is a DISPLAY price
    # only ("from ৳270") and cart_items.variant_id becomes required. Enforced in
    # the service layer — the rule spans two tables.
    base_price: Mapped[int] = mapped_column(Money, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_veg: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    prep_time_mins: Mapped[int | None] = mapped_column(SmallInteger)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    # Soft delete: order history and analytics must survive a menu cleanup.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    category: Mapped["MenuCategory"] = relationship(back_populates="items", lazy="raise")
    variants: Mapped[list["ItemVariant"]] = relationship(back_populates="item", lazy="raise")
    add_ons: Mapped[list["ItemAddOn"]] = relationship(back_populates="item", lazy="raise")

    __table_args__ = (
        CheckConstraint("base_price >= 0", name="ck_menu_items_price"),
        ForeignKeyConstraint(
            ["category_id", "restaurant_id"],
            ["menu_categories.id", "menu_categories.restaurant_id"],
            name="fk_menu_items_category",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "restaurant_id", name="uq_menu_items_id_restaurant"),
        Index(
            "ix_menu_items_category",
            "category_id",
            "sort_order",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_menu_items_restaurant_available",
            "restaurant_id",
            postgresql_where=text("deleted_at IS NULL AND is_available"),
        ),
        Index(
            "ix_menu_items_search",
            text("to_tsvector('simple', name || ' ' || coalesce(description, ''))"),
            postgresql_using="gin",
        ),
    )


class ItemVariant(Base, UUIDPrimaryKey):
    """Decision D4: `price` REPLACES base_price — it is absolute, not a delta."""

    __tablename__ = "item_variants"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[int] = mapped_column(Money, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))

    item: Mapped["MenuItem"] = relationship(back_populates="variants", lazy="raise")

    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_item_variants_price"),
        UniqueConstraint("menu_item_id", "name", name="uq_item_variants_name"),
        # Lets cart_items prove the chosen variant belongs to the chosen item.
        UniqueConstraint("id", "menu_item_id", name="uq_item_variants_id_item"),
        Index(
            "uq_item_variants_one_default",
            "menu_item_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class ItemAddOn(Base, UUIDPrimaryKey):
    """Decision D4: `price` ADDS to the resolved unit price."""

    __tablename__ = "item_add_ons"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[int] = mapped_column(Money, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))

    item: Mapped["MenuItem"] = relationship(back_populates="add_ons", lazy="raise")

    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_item_add_ons_price"),
        UniqueConstraint("menu_item_id", "name", name="uq_item_add_ons_name"),
        UniqueConstraint("id", "menu_item_id", name="uq_item_add_ons_id_item"),
    )
