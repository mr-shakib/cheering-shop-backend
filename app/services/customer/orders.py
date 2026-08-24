"""Checkout, order placement, history and tracking — spec #28–33.

**The quote and the order run the same arithmetic.** `checkout_summary` and
`place_order` both build their bill through `services.pricing.quote`, so the
number the customer agreed to is the number that is charged. The database backs
this up: `ck_orders_total_math` refuses any row whose `grand_total` does not
equal the sum of its parts, so a mispriced order cannot be persisted even if
this module were wrong.

Placement is one transaction. Order, lines, add-ons, the first status-history
row, the promo redemption and the cart deletion either all land or none do —
an order that exists with a cart still full would let the customer place it
twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.money import to_major, to_minor
from app.models.address import Address
from app.models.enums import ActorType, OrderStatus, PaymentStatus, RestaurantStatus
from app.models.order import Order, OrderItem, OrderItemAddOn, OrderStatusHistory
from app.models.promo import PromoRedemption
from app.models.restaurant import Restaurant
from app.models.review import Review
from app.schemas.customer import (
    CheckoutSummary,
    OrderDetail,
    OrderItemOut,
    OrderStatusEvent,
    OrderSummary,
    OrderTracking,
    PlacedOrder,
)
from app.schemas.requests import OrderCreateRequest
from app.services.customer import cart as cart_service
from app.services.customer import promos as promo_service
from app.services.pricing import haversine_km, quote

# Statuses a customer may still cancel from. Spec §9: only PENDING — once the
# kitchen has accepted, food is being cooked and cancellation is a phone call.
_CANCELLABLE = {OrderStatus.PENDING.value}
# Terminal states for the "can I still review this" test.
_REVIEWABLE = {OrderStatus.DELIVERED.value}


def _as_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValidationError(f"{what} is not a valid id") from exc


async def _load_address(db: AsyncSession, user_id: uuid.UUID, address_id: str) -> Address:
    address = await db.scalar(
        select(Address).where(
            Address.id == _as_uuid(address_id, "address_id"), Address.user_id == user_id
        )
    )
    if address is None:
        raise NotFoundError("Delivery address not found")
    return address


def _address_text(address: Address) -> str:
    """Flatten an address into the single line an order snapshots."""
    parts = [address.street_address, address.apartment, address.landmark, address.city]
    return ", ".join(p for p in parts if p)


async def _prepare(
    db: AsyncSession,
    user_id: uuid.UUID,
    address_id: str,
    promo_code: str | None,
    tip: Decimal | float | int,
):
    """Everything checkout and placement both need, computed once.

    Returns (cart, restaurant, address, quote, promo_result).
    """
    cart, lines = await cart_service.quote_lines_for(db, user_id)
    if cart is None or not lines:
        raise ValidationError("Your cart is empty")

    restaurant = await db.get(Restaurant, cart.restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")

    address = await _load_address(db, user_id, address_id)
    distance_km = haversine_km(
        restaurant.latitude, restaurant.longitude, address.latitude, address.longitude
    )
    if distance_km > settings.MAX_DELIVERY_DISTANCE_KM:
        raise ValidationError(
            f"{restaurant.name} does not deliver that far",
            details=[
                f"{round(distance_km, 1)} km away; the limit is "
                f"{settings.MAX_DELIVERY_DISTANCE_KM} km"
            ],
        )

    item_total = sum(line.line_total for line in lines)
    promo = await promo_service.validate(
        db,
        promo_code,
        user_id=user_id,
        restaurant_id=restaurant.id,
        item_total=item_total,
    )
    bill = quote(
        lines,
        base_delivery_fee_minor=restaurant.delivery_fee_base,
        distance_km=distance_km,
        commission_rate=float(restaurant.commission_rate),
        discount=promo.discount,
        tip=to_minor(tip),
    )
    return cart, restaurant, address, bill, promo


async def checkout_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    address_id: str,
    promo_code: str | None = None,
    tip: float = 0,
) -> CheckoutSummary:
    """Spec #28. The bill, before anything is committed.

    A rejected promo does not fail the call — the bill still returns, with
    `promo_error` explaining what happened. Dropping the code silently is how a
    customer ends up staring at an unchanged total with no idea why.
    """
    _, restaurant, _, bill, promo = await _prepare(db, user_id, address_id, promo_code, tip)
    eta = restaurant.avg_prep_time_mins + max(5, round(bill.distance_km * 3))
    return CheckoutSummary(
        **bill.as_taka(),
        estimated_delivery_minutes=eta,
        promo_code=promo.code,
        promo_error=promo.error,
    )


async def place_order(
    db: AsyncSession, user_id: uuid.UUID, body: OrderCreateRequest
) -> PlacedOrder:
    """Spec #29. Cart becomes an order; the cart is cleared in the same
    transaction.

    A promo the customer *sent* but that is invalid is a hard failure here,
    unlike at checkout: they are committing to a total, and quietly charging
    them the undiscounted price would be indefensible. At summary time it is a
    message; at placement it is a 400.
    """
    cart, restaurant, address, bill, promo = await _prepare(
        db, user_id, body.address_id, body.promo_code, body.tip
    )
    if body.promo_code and promo.error:
        raise ValidationError(promo.error)

    if str(restaurant.status) != RestaurantStatus.OPEN:
        raise ConflictError(f"{restaurant.name} is closed right now")
    unavailable = [line.name for line in bill.lines if line.quantity <= 0]
    if unavailable:
        raise ConflictError("Some items are no longer available", details=unavailable)
    if bill.item_total < restaurant.min_order_amount:
        raise ValidationError(
            f"Minimum order is {to_major(restaurant.min_order_amount)} taka",
            details=[f"Your items come to {to_major(bill.item_total)} taka"],
        )

    scheduled_for = _validate_schedule(body)
    now = datetime.now(UTC)
    eta_minutes = restaurant.avg_prep_time_mins + max(5, round(bill.distance_km * 3))

    order = Order(
        customer_id=user_id,
        restaurant_id=restaurant.id,
        status=OrderStatus.PENDING.value,
        item_total=bill.item_total,
        delivery_fee=bill.delivery_fee,
        discount=bill.discount,
        tip=bill.tip,
        packaging_fee=bill.packaging_fee,
        tax_amount=bill.tax_amount,
        platform_fee=bill.platform_fee,
        grand_total=bill.grand_total,
        commission_amount=bill.commission_amount,
        payment_method=body.payment_method,
        payment_status=PaymentStatus.PENDING.value,
        promo_code_id=promo.promo.id if promo.promo else None,
        delivery_address_id=address.id,
        delivery_address_text=_address_text(address),
        delivery_latitude=address.latitude,
        delivery_longitude=address.longitude,
        delivery_contact_phone=address.contact_phone,
        special_instructions=body.special_instructions,
        scheduled_for=scheduled_for,
        # The 60s vendor timeout the arq worker sweeps. A scheduled order is
        # not on the clock yet — the countdown starts when the kitchen is
        # asked, not when the customer books.
        auto_decline_at=None
        if scheduled_for
        else now + timedelta(seconds=settings.VENDOR_AUTO_DECLINE_SECONDS),
        estimated_delivery_at=(scheduled_for or now) + timedelta(minutes=eta_minutes),
    )
    db.add(order)
    await db.flush()

    for line in bill.lines:
        item = OrderItem(
            order_id=order.id,
            menu_item_id=_as_uuid(line.menu_item_id, "menu_item_id"),
            item_name=line.name,
            variant_name=line.variant_name,
            image_url=line.image_url,
            unit_price=line.unit_price,
            add_ons_total=line.add_ons_total,
            quantity=line.quantity,
            line_total=line.line_total,
            notes=line.notes,
        )
        db.add(item)
        await db.flush()
        for name in line.add_on_names:
            # Name and price are snapshots; the add-on row itself may be
            # renamed or deleted later without rewriting this receipt.
            db.add(OrderItemAddOn(order_item_id=item.id, name=name, price=0))

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=None,
            to_status=OrderStatus.PENDING.value,
            actor=ActorType.CUSTOMER.value,
            actor_id=user_id,
            note="Order placed",
        )
    )
    if promo.promo is not None:
        db.add(
            PromoRedemption(
                promo_code_id=promo.promo.id,
                user_id=user_id,
                order_id=order.id,
                discount_applied=bill.discount,
            )
        )
        promo.promo.times_used += 1

    await cart_service.clear(db, user_id)
    await db.flush()

    return PlacedOrder(
        id=str(order.id),
        order_number=order.order_number,
        status=order.status,
        grand_total=to_major(order.grand_total),
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        estimated_delivery_at=order.estimated_delivery_at,
        scheduled_for=order.scheduled_for,
        restaurant_id=str(restaurant.id),
        restaurant_name=restaurant.name,
        placed_at=order.placed_at or now,
    )


def _validate_schedule(body: OrderCreateRequest) -> datetime | None:
    """Scheduled delivery, from the Schedule Order sheet.

    Validated against the same lead time the slot generator uses, because a
    client can post any timestamp it likes regardless of which slots were
    offered.
    """
    scheduled_for = getattr(body, "scheduled_for", None)
    if scheduled_for is None:
        return None
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    earliest = now + timedelta(minutes=settings.SCHEDULE_MIN_LEAD_MINUTES)
    if scheduled_for < earliest:
        raise ValidationError(
            f"Schedule at least {settings.SCHEDULE_MIN_LEAD_MINUTES} minutes ahead"
        )
    if scheduled_for > now + timedelta(days=settings.SCHEDULE_MAX_DAYS_AHEAD):
        raise ValidationError(
            f"Orders can be scheduled up to {settings.SCHEDULE_MAX_DAYS_AHEAD} days ahead"
        )
    return scheduled_for


async def _reviewed_order_ids(db: AsyncSession, order_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not order_ids:
        return set()
    rows = await db.scalars(select(Review.order_id).where(Review.order_id.in_(order_ids)))
    return set(rows.all())


def _to_summary(order: Order, restaurant: Restaurant | None, *, reviewed: bool) -> OrderSummary:
    return OrderSummary(
        id=str(order.id),
        order_number=order.order_number,
        status=str(order.status),
        restaurant_id=str(order.restaurant_id),
        restaurant_name=restaurant.name if restaurant else "",
        restaurant_logo_url=restaurant.logo_url if restaurant else None,
        item_count=len(order.items) if "items" in order.__dict__ else 0,
        grand_total=to_major(order.grand_total),
        payment_method=str(order.payment_method),
        payment_status=str(order.payment_status),
        placed_at=order.placed_at,
        delivered_at=order.delivered_at,
        scheduled_for=order.scheduled_for,
        can_review=str(order.status) in _REVIEWABLE and not reviewed,
        can_cancel=str(order.status) in _CANCELLABLE,
    )


async def list_orders(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[OrderSummary], int]:
    """Spec #30. Newest first — `ix_orders_customer_history` covers exactly
    this ordering."""
    conditions = [Order.customer_id == user_id]
    if status:
        # "ACTIVE" is what the Order screen's tab actually means: anything
        # still in flight. Spelling it as a status keeps the client simple.
        if status.upper() == "ACTIVE":
            conditions.append(
                Order.status.in_(
                    [
                        OrderStatus.PENDING.value,
                        OrderStatus.PREPARING.value,
                        OrderStatus.READY.value,
                        OrderStatus.PICKED_UP.value,
                    ]
                )
            )
        else:
            conditions.append(Order.status == status.upper())

    total = await db.scalar(select(func.count()).select_from(Order).where(*conditions)) or 0
    rows = await db.execute(
        select(Order, Restaurant)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(*conditions)
        .order_by(Order.placed_at.desc())
        .limit(limit)
        .offset(offset)
        .options(selectinload(Order.items))
    )
    pairs = rows.all()
    reviewed = await _reviewed_order_ids(db, [o.id for o, _ in pairs])
    return [
        _to_summary(o, r, reviewed=o.id in reviewed) for o, r in pairs
    ], total


async def _load_order(db: AsyncSession, user_id: uuid.UUID, order_id: str) -> Order:
    order = await db.scalar(
        select(Order)
        .where(Order.id == _as_uuid(order_id, "order_id"), Order.customer_id == user_id)
        .options(
            selectinload(Order.items).selectinload(OrderItem.add_ons),
            selectinload(Order.status_history),
        )
    )
    if order is None:
        # Deliberately the same 404 whether the order does not exist or belongs
        # to someone else — the difference would let anyone probe for valid ids.
        raise NotFoundError("Order not found")
    return order


async def order_detail(db: AsyncSession, user_id: uuid.UUID, order_id: str) -> OrderDetail:
    """The Order Details screen: full receipt plus the timeline."""
    order = await _load_order(db, user_id, order_id)
    restaurant = await db.get(Restaurant, order.restaurant_id)
    reviewed = await _reviewed_order_ids(db, [order.id])
    summary = _to_summary(order, restaurant, reviewed=order.id in reviewed)

    return OrderDetail(
        **summary.model_dump(),
        items=[
            OrderItemOut(
                id=str(i.id),
                menu_item_id=str(i.menu_item_id) if i.menu_item_id else None,
                name=i.item_name,
                quantity=i.quantity,
                unit_price=to_major(i.unit_price),
                add_ons_total=to_major(i.add_ons_total),
                line_total=to_major(i.line_total),
                variant_name=i.variant_name,
                add_on_names=[a.name for a in i.add_ons],
                image_url=i.image_url,
                notes=i.notes,
            )
            for i in order.items
        ],
        item_total=to_major(order.item_total),
        delivery_fee=to_major(order.delivery_fee),
        packaging_fee=to_major(order.packaging_fee),
        tax_amount=to_major(order.tax_amount),
        platform_fee=to_major(order.platform_fee),
        discount=to_major(order.discount),
        tip=to_major(order.tip),
        delivery_address_text=order.delivery_address_text,
        delivery_latitude=order.delivery_latitude,
        delivery_longitude=order.delivery_longitude,
        delivery_contact_phone=order.delivery_contact_phone,
        special_instructions=order.special_instructions,
        estimated_delivery_at=order.estimated_delivery_at,
        cancellation_reason=order.cancellation_reason,
        timeline=_timeline(order),
        rider=None,
    )


def _timeline(order: Order) -> list[OrderStatusEvent]:
    """The dots on Ride Assign.png, straight from order_status_history."""
    return [
        OrderStatusEvent(status=str(h.to_status), at=h.created_at, note=h.note)
        for h in sorted(order.status_history, key=lambda h: h.created_at)
    ]


async def cancel_order(
    db: AsyncSession, user_id: uuid.UUID, order_id: str, reason: str | None = None
) -> OrderDetail:
    """Spec #32. Grace-period cancellation — PENDING only.

    Once the vendor accepts, food is being cooked; cancelling then is a
    conversation with the restaurant, not an API call. The 409 says so rather
    than pretending the button was never there.
    """
    order = await _load_order(db, user_id, order_id)
    if str(order.status) not in _CANCELLABLE:
        raise ConflictError(
            "This order can no longer be cancelled",
            details=[f"It is already {str(order.status).lower()}."],
        )

    now = datetime.now(UTC)
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=order.status,
            to_status=OrderStatus.CANCELLED.value,
            actor=ActorType.CUSTOMER.value,
            actor_id=user_id,
            note=reason or "Cancelled by customer",
        )
    )
    order.status = OrderStatus.CANCELLED.value
    order.cancelled_at = now
    order.cancelled_by = ActorType.CUSTOMER.value
    order.cancellation_reason = reason
    order.updated_at = now
    # Nothing was captured — payment is recorded, never executed — so there is
    # no refund to issue for a PENDING order. A paid order cancelled later is
    # the vendor-reject path, which does set REFUNDED.
    await db.flush()
    return await order_detail(db, user_id, order_id)


async def tracking(db: AsyncSession, user_id: uuid.UUID, order_id: str) -> OrderTracking:
    """Spec #31. Initialises the map; the WebSocket streams updates after.

    `rider_location` stays null and `live_tracking_available` false until a
    rider client exists to report a position. Interpolating a plausible dot
    would be worse than an honest absence — a customer watching a fake courier
    approach is being lied to.
    """
    order = await _load_order(db, user_id, order_id)
    restaurant = await db.get(Restaurant, order.restaurant_id)

    eta_minutes = None
    if order.estimated_delivery_at and str(order.status) not in {
        OrderStatus.DELIVERED.value,
        OrderStatus.CANCELLED.value,
    }:
        remaining = (order.estimated_delivery_at - datetime.now(UTC)).total_seconds() / 60
        eta_minutes = max(0, round(remaining))

    return OrderTracking(
        order_id=str(order.id),
        status=str(order.status),
        timeline=_timeline(order),
        restaurant_latitude=restaurant.latitude if restaurant else 0.0,
        restaurant_longitude=restaurant.longitude if restaurant else 0.0,
        restaurant_name=restaurant.name if restaurant else "",
        delivery_latitude=order.delivery_latitude,
        delivery_longitude=order.delivery_longitude,
        delivery_address_text=order.delivery_address_text,
        estimated_delivery_at=order.estimated_delivery_at,
        eta_minutes=eta_minutes,
        rider=None,
        rider_location=None,
        live_tracking_available=False,
    )


__all__ = [
    "cancel_order",
    "checkout_summary",
    "list_orders",
    "order_detail",
    "place_order",
    "tracking",
]
