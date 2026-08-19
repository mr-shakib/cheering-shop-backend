"""Orders, line items, and the status audit trail."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.address import GEO_FROM_LATLNG
from app.models.base import Base, GeoPoint, Money, UUIDPrimaryKey
from app.models.enums import (
    ActorTypeType,
    OrderStatusType,
    PaymentMethodType,
    PaymentStatusType,
    UserRoleType,
)


class Order(Base, UUIDPrimaryKey):
    __tablename__ = "orders"

    order_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), unique=True, nullable=False
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_role: Mapped[str] = mapped_column(
        UserRoleType, nullable=False, server_default=text("'CUSTOMER'")
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="RESTRICT"), nullable=False
    )
    rider_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    rider_role: Mapped[str | None] = mapped_column(UserRoleType)

    status: Mapped[str] = mapped_column(
        OrderStatusType, nullable=False, server_default=text("'PENDING'")
    )

    # --- Money, all paisa (decision D6) ---------------------------------
    item_total: Mapped[int] = mapped_column(Money, nullable=False)
    delivery_fee: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    discount: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    tip: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    packaging_fee: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    tax_amount: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    platform_fee: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    grand_total: Mapped[int] = mapped_column(Money, nullable=False)
    # Snapshot — restaurants.commission_rate is mutable and must not rewrite
    # historical earnings. Vendor payout == item_total - commission_amount.
    commission_amount: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))

    payment_method: Mapped[str] = mapped_column(PaymentMethodType, nullable=False)
    payment_status: Mapped[str] = mapped_column(
        PaymentStatusType, nullable=False, server_default=text("'PENDING'")
    )
    payment_reference: Mapped[str | None] = mapped_column(String(255))

    promo_code_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promo_codes.id", ondelete="SET NULL")
    )

    # --- Handoff proof (decision D3, amended) ----------------------------
    # HMAC-SHA256(pepper, order_id || pin). Issued at READY, not at creation.
    rider_pin_hash: Mapped[str | None] = mapped_column(Text)
    # Fernet ciphertext of the same PIN. The vendor app's handoff screen
    # displays the code while the order is READY ("hand this code to your
    # rider"), so the plaintext must be recoverable — the HMAC alone cannot be
    # reversed. Encrypted like totp_secret: a database dump without the app key
    # yields nothing. Exposed to the owning vendor only, and only while READY.
    rider_pin_cipher: Mapped[str | None] = mapped_column(Text)
    rider_pin_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handoff_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )

    # --- Delivery address SNAPSHOT ---------------------------------------
    # The customer may edit or delete the address later; a delivered order must
    # still record where it actually went.
    delivery_address_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("addresses.id", ondelete="SET NULL")
    )
    delivery_address_text: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_location: Mapped[object] = mapped_column(
        GeoPoint,
        Computed(
            GEO_FROM_LATLNG.format(lng="delivery_longitude", lat="delivery_latitude"),
            persisted=True,
        ),
        nullable=True,
    )
    delivery_contact_phone: Mapped[str | None] = mapped_column(String(20))
    special_instructions: Mapped[str | None] = mapped_column(String(500))

    # --- Lifecycle (spec §8) ---------------------------------------------
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # The 60s vendor timeout the arq worker sweeps (spec §9).
    auto_decline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[str | None] = mapped_column(ActorTypeType)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255))
    estimated_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", lazy="raise")
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="order", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint("customer_role = 'CUSTOMER'", name="ck_orders_customer_role"),
        ForeignKeyConstraint(
            ["customer_id", "customer_role"],
            ["users.id", "users.role"],
            name="fk_orders_customer",
            ondelete="RESTRICT",
        ),
        CheckConstraint("rider_role IS NULL OR rider_role = 'RIDER'", name="ck_orders_rider_role"),
        CheckConstraint("(rider_id IS NULL) = (rider_role IS NULL)", name="ck_orders_rider_pair"),
        ForeignKeyConstraint(
            ["rider_id", "rider_role"],
            ["users.id", "users.role"],
            name="fk_orders_rider",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "item_total >= 0 AND delivery_fee >= 0 AND discount >= 0 "
            "AND tip >= 0 AND packaging_fee >= 0 AND tax_amount >= 0 "
            "AND platform_fee >= 0 AND commission_amount >= 0 AND grand_total >= 0",
            name="ck_orders_money_nonneg",
        ),
        # The arithmetic contract of GET /checkout/summary. A mispriced order
        # cannot be persisted at all.
        CheckConstraint(
            "grand_total = item_total + delivery_fee + packaging_fee "
            "+ tax_amount + platform_fee + tip - discount",
            name="ck_orders_total_math",
        ),
        CheckConstraint("commission_amount <= item_total", name="ck_orders_commission"),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL)", name="ck_orders_cancelled"
        ),
        CheckConstraint(
            "status <> 'DELIVERED' OR delivered_at IS NOT NULL", name="ck_orders_delivered"
        ),
        CheckConstraint(
            "status NOT IN ('PICKED_UP', 'DELIVERED') OR rider_id IS NOT NULL",
            name="ck_orders_rider_required",
        ),
        Index("ix_orders_vendor_queue", "restaurant_id", "status", text("placed_at DESC")),
        Index("ix_orders_customer_history", "customer_id", text("placed_at DESC")),
        Index(
            "ix_orders_rider", "rider_id", "status", postgresql_where=text("rider_id IS NOT NULL")
        ),
        # Tiny partial index — only unaccepted orders qualify, so the sweeper
        # scans almost nothing however large the table grows.
        Index(
            "ix_orders_auto_decline",
            "auto_decline_at",
            postgresql_where=text("status = 'PENDING' AND auto_decline_at IS NOT NULL"),
        ),
        Index(
            "ix_orders_analytics",
            "restaurant_id",
            "delivered_at",
            postgresql_where=text("status = 'DELIVERED'"),
        ),
    )


class OrderItem(Base, UUIDPrimaryKey):
    """[EXTENDED] The single most important omission in spec §6.

    Every user-visible field is a snapshot taken at purchase time, so repricing
    a menu can never rewrite the history of a delivered order.
    """

    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="SET NULL")
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_variants.id", ondelete="SET NULL")
    )
    item_name: Mapped[str] = mapped_column(String(180), nullable=False)
    variant_name: Mapped[str | None] = mapped_column(String(120))
    image_url: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[int] = mapped_column(Money, nullable=False)
    add_ons_total: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    line_total: Mapped[int] = mapped_column(Money, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255))

    order: Mapped["Order"] = relationship(back_populates="items", lazy="raise")
    add_ons: Mapped[list["OrderItemAddOn"]] = relationship(
        back_populates="order_item", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_qty"),
        CheckConstraint(
            "unit_price >= 0 AND add_ons_total >= 0 AND line_total >= 0",
            name="ck_order_items_money",
        ),
        CheckConstraint(
            "line_total = (unit_price + add_ons_total) * quantity", name="ck_order_items_math"
        ),
        Index("ix_order_items_order", "order_id"),
        Index("ix_order_items_menu_item", "menu_item_id"),
    )


class OrderItemAddOn(Base, UUIDPrimaryKey):
    """[EXTENDED] Add-ons chosen per line, snapshotted."""

    __tablename__ = "order_item_add_ons"

    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False
    )
    add_on_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_add_ons.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[int] = mapped_column(Money, nullable=False)

    order_item: Mapped["OrderItem"] = relationship(back_populates="add_ons", lazy="raise")

    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_order_item_add_ons_price"),
        Index("ix_order_item_add_ons_item", "order_item_id"),
    )


class OrderStatusHistory(Base, UUIDPrimaryKey):
    """[EXTENDED] Powers the GET /orders/{id}/tracking timeline and settles
    "who cancelled this and when" in a dispute."""

    __tablename__ = "order_status_history"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(OrderStatusType)
    to_status: Mapped[str] = mapped_column(OrderStatusType, nullable=False)
    actor: Mapped[str] = mapped_column(ActorTypeType, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    order: Mapped["Order"] = relationship(back_populates="status_history", lazy="raise")

    __table_args__ = (Index("ix_order_status_history_order", "order_id", "created_at"),)


_ = UniqueConstraint  # re-exported for symmetry with the DDL
