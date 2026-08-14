"""Cart and cart items.

This is where the spec's headline invariant is enforced. See docs §3.1 — spec
§10 claims the single-restaurant rule is enforced at the database level, but
`restaurant_id` on the cart alone does not do it. The composite FK pair below
does, and `db/verify_constraints.sql` proves both bypass attempts are rejected.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
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

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Cart(Base, UUIDPrimaryKey, TimestampMixin):
    """Decision D5: surrogate `id` PK with UNIQUE(user_id).

    Spec §6 named user_id as the PK; UNIQUE(user_id) is an identical guarantee
    while keeping one shape for the ORM base class and leaving room for group or
    scheduled carts later.
    """

    __tablename__ = "carts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", lazy="raise", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # FK target for the cross-restaurant guard on cart_items.
        UniqueConstraint("id", "restaurant_id", name="uq_carts_id_restaurant"),
    )


class CartItem(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "cart_items"

    cart_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Shared by BOTH composite FKs below. That sharing is the whole mechanism:
    # an item from another restaurant cannot satisfy both constraints at once.
    restaurant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    menu_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Sorted, hashed add-on id list, so "same item, same options" collapses into
    # one row while "same item, different options" stays separate.
    add_ons_fingerprint: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    notes: Mapped[str | None] = mapped_column(String(255))

    cart: Mapped["Cart"] = relationship(back_populates="items", lazy="raise")
    add_ons: Mapped[list["CartItemAddOn"]] = relationship(
        back_populates="cart_item", lazy="raise", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_cart_items_qty"),
        ForeignKeyConstraint(
            ["cart_id", "restaurant_id"],
            ["carts.id", "carts.restaurant_id"],
            name="fk_cart_items_cart",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["menu_item_id", "restaurant_id"],
            ["menu_items.id", "menu_items.restaurant_id"],
            name="fk_cart_items_menu_item",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["variant_id", "menu_item_id"],
            ["item_variants.id", "item_variants.menu_item_id"],
            name="fk_cart_items_variant",
            ondelete="CASCADE",
        ),
        # NULLS NOT DISTINCT (PG15+) so a NULL variant still collapses correctly.
        UniqueConstraint(
            "cart_id",
            "menu_item_id",
            "variant_id",
            "add_ons_fingerprint",
            name="uq_cart_items_config",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_cart_items_cart", "cart_id"),
    )


class CartItemAddOn(Base):
    """[EXTENDED] N:M. menu_item_id is carried so the composite FK can prove the
    add-on belongs to the item it is attached to."""

    __tablename__ = "cart_item_add_ons"

    cart_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cart_items.id", ondelete="CASCADE"), primary_key=True
    )
    add_on_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    menu_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    cart_item: Mapped["CartItem"] = relationship(back_populates="add_ons", lazy="raise")

    __table_args__ = (
        ForeignKeyConstraint(
            ["add_on_id", "menu_item_id"],
            ["item_add_ons.id", "item_add_ons.menu_item_id"],
            name="fk_cart_item_add_ons_addon",
            ondelete="CASCADE",
        ),
    )
