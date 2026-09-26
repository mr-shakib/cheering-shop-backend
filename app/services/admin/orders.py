"""The platform-wide order table and the operator's order actions.

The vendor and customer order modules are each scoped to one party; this one
sees every order, so it never takes an owner to filter by. The state machine is
still `ORDER_TRANSITIONS`: an administrator can do more than a vendor can, but
not what the lifecycle forbids. A PICKED_UP order cannot be cancelled here
either — the food is in a bag on a motorcycle, and "cancelled" would not bring
it back.

Refunds are recorded, not executed, exactly as the vendor-reject path does it:
no payment gateway is wired up, so REFUNDED means "owed back and on record".
"""

import uuid
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.money import to_major
from app.models.enums import ORDER_TRANSITIONS, ActorType, OrderStatus, PaymentMethod
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.restaurant import Restaurant
from app.models.rider import RiderProfile
from app.models.user import User
from app.schemas.admin import (
    AdminOrderActions,
    AdminOrderCustomer,
    AdminOrderDetail,
    AdminOrderEvent,
    AdminOrderMoney,
    AdminOrderPayment,
    AdminOrderRider,
    AdminOrderRow,
    AdminOrderVendor,
    AdminRiderLocation,
)
from app.services.admin.common import (
    business_type_of,
    day_window,
    like_pattern,
    order_number_from,
    parse_uuid,
)
from app.services.pricing import haversine_km
from app.services.rider import tracking as rider_tracking
from app.services.rider.dispatch import ASSIGNABLE
from app.services.vendor.orders import parse_status_filter, to_detail

log = structlog.get_logger()

_Customer = aliased(User, name="customer")
_Rider = aliased(User, name="rider")


def _rows_query() -> Select:
    """Order plus the names every table row shows, in one round trip."""
    return (
        select(
            Order,
            _Customer.full_name,
            Restaurant.name,
            business_type_of(Order.restaurant_id),
            _Rider.full_name,
        )
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .outerjoin(_Customer, _Customer.id == Order.customer_id)
        .outerjoin(_Rider, _Rider.id == Order.rider_id)
    )


def _to_row(
    order: Order,
    customer_name: str | None,
    restaurant_name: str,
    business_type: str | None,
    rider_name: str | None,
) -> AdminOrderRow:
    return AdminOrderRow(
        id=str(order.id),
        order_number=order.order_number,
        status=str(order.status),
        payment_method=str(order.payment_method),
        payment_status=str(order.payment_status),
        customer_id=str(order.customer_id),
        customer_name=customer_name,
        restaurant_id=str(order.restaurant_id),
        restaurant_name=restaurant_name,
        business_type=business_type,
        rider_id=str(order.rider_id) if order.rider_id else None,
        rider_name=rider_name,
        grand_total=to_major(order.grand_total),
        commission_amount=to_major(order.commission_amount),
        placed_at=order.placed_at,
        delivered_at=order.delivered_at,
        cancelled_at=order.cancelled_at,
    )


async def list_orders(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    payment_method: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    customer_id: str | None = None,
    restaurant_id: str | None = None,
    rider_id: str | None = None,
) -> tuple[list[AdminOrderRow], int]:
    """Newest first. Every filter is optional and they combine with AND.

    `status` takes what the vendor queue takes — one status, a comma list, or a
    tab name — so the console and the vendor app agree on what "PREPARING"
    means (PREPARING and READY). The date range filters on `placed_at`.
    """
    conditions: list[ColumnElement[bool]] = []
    statuses = parse_status_filter(status)
    if statuses:
        conditions.append(Order.status.in_(statuses))
    if payment_method:
        method = payment_method.strip().upper()
        if method not in PaymentMethod.__members__:
            raise ValidationError(
                f"Unknown payment method '{payment_method}'",
                details=[f"Expected one of: {', '.join(PaymentMethod.__members__)}"],
            )
        conditions.append(Order.payment_method == method)
    start, end = day_window(date_from, date_to)
    if start:
        conditions.append(Order.placed_at >= start)
    if end:
        conditions.append(Order.placed_at < end)
    for raw, column, what in (
        (customer_id, Order.customer_id, "customer_id"),
        (restaurant_id, Order.restaurant_id, "restaurant_id"),
        (rider_id, Order.rider_id, "rider_id"),
    ):
        parsed = parse_uuid(raw, what)
        if parsed:
            conditions.append(column == parsed)
    if q and q.strip():
        pattern = like_pattern(q.strip())
        matches: list[ColumnElement[bool]] = [
            _Customer.full_name.ilike(pattern),
            _Customer.phone.ilike(pattern),
            Restaurant.name.ilike(pattern),
        ]
        number = order_number_from(q)
        if number is not None:
            matches.append(Order.order_number == number)
        conditions.append(or_(*matches))

    base = _rows_query().where(*conditions)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(base.order_by(Order.placed_at.desc()).limit(limit).offset(offset))
    return [_to_row(*row) for row in result.all()], total


async def recent_orders(db: AsyncSession, n: int) -> list[AdminOrderRow]:
    result = await db.execute(_rows_query().order_by(Order.placed_at.desc()).limit(n))
    return [_to_row(*row) for row in result.all()]


# ---------------------------------------------------------------------------
# The drawer
# ---------------------------------------------------------------------------


async def _load(db: AsyncSession, order_id: uuid.UUID, *, for_update: bool = False) -> Order:
    query = (
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.items).selectinload(OrderItem.add_ons),
            selectinload(Order.status_history),
        )
    )
    if for_update:
        query = query.with_for_update(of=Order)
    order = await db.scalar(query)
    if order is None:
        raise NotFoundError("Order not found")
    return order


def _actions(order: Order) -> AdminOrderActions:
    status = OrderStatus(str(order.status))
    return AdminOrderActions(
        can_assign_rider=status in ASSIGNABLE,
        can_cancel=OrderStatus.CANCELLED in ORDER_TRANSITIONS.get(status, set()),
        can_refund=str(order.payment_status) == "PAID",
        can_force_deliver=status == OrderStatus.PICKED_UP and order.rider_id is not None,
    )


async def get_detail(db: AsyncSession, order_id: uuid.UUID) -> AdminOrderDetail:
    order = await _load(db, order_id)
    return await _detail(db, order)


async def _detail(db: AsyncSession, order: Order) -> AdminOrderDetail:
    customer = await db.get(User, order.customer_id)
    restaurant = await db.get(Restaurant, order.restaurant_id)
    if restaurant is None:  # pragma: no cover - orders.restaurant_id is RESTRICT
        raise NotFoundError("Order not found")
    business_type = await db.scalar(select(business_type_of(restaurant.id)))

    rider = rider_user = None
    if order.rider_id:
        rider_user = await db.get(User, order.rider_id)
        profile = await db.get(RiderProfile, order.rider_id)
        if rider_user:
            rider = AdminOrderRider(
                id=str(rider_user.id),
                full_name=rider_user.full_name,
                phone=rider_user.phone,
                vehicle_type=profile.vehicle_type if profile else None,
                rating_avg=float(profile.rating_avg) if profile else None,
            )

    location = None
    position = await rider_tracking.position_for_order(db, order)
    if rider_tracking.is_fresh(position) and position is not None:
        location = AdminRiderLocation(
            latitude=position.latitude,
            longitude=position.longitude,
            updated_at=position.updated_at,
            distance_to_dropoff_km=round(
                haversine_km(
                    position.latitude,
                    position.longitude,
                    order.delivery_latitude,
                    order.delivery_longitude,
                ),
                2,
            ),
        )

    row = _to_row(
        order,
        customer.full_name if customer else None,
        restaurant.name,
        business_type,
        rider_user.full_name if rider_user else None,
    )
    kitchen_view = to_detail(order, customer)
    return AdminOrderDetail(
        **row.model_dump(),
        timeline=[
            AdminOrderEvent(
                status=str(h.to_status), at=h.created_at, actor=str(h.actor), note=h.note
            )
            for h in sorted(order.status_history, key=lambda h: h.created_at)
        ],
        customer=AdminOrderCustomer(
            id=str(order.customer_id),
            full_name=customer.full_name if customer else None,
            email=customer.email if customer else None,
            phone=customer.phone if customer else None,
            delivery_contact_phone=order.delivery_contact_phone,
            delivery_address_text=order.delivery_address_text,
            delivery_latitude=order.delivery_latitude,
            delivery_longitude=order.delivery_longitude,
        ),
        vendor=AdminOrderVendor(
            id=str(restaurant.id),
            name=restaurant.name,
            phone=restaurant.phone,
            logo_url=restaurant.logo_url,
            address_line=restaurant.address_line,
            business_type=business_type,
        ),
        rider=rider,
        rider_location=location,
        money=AdminOrderMoney(
            item_total=to_major(order.item_total),
            delivery_fee=to_major(order.delivery_fee),
            packaging_fee=to_major(order.packaging_fee),
            tax_amount=to_major(order.tax_amount),
            platform_fee=to_major(order.platform_fee),
            tip=to_major(order.tip),
            discount=to_major(order.discount),
            grand_total=to_major(order.grand_total),
            commission_amount=to_major(order.commission_amount),
            vendor_payout=to_major(order.item_total - order.commission_amount),
        ),
        payment=AdminOrderPayment(
            method=str(order.payment_method),
            status=str(order.payment_status),
            reference=order.payment_reference,
            refunded_at=order.refunded_at,
            refunded_by=str(order.refunded_by) if order.refunded_by else None,
            refund_reason=order.refund_reason,
        ),
        items=kitchen_view.items,
        special_instructions=order.special_instructions,
        scheduled_for=order.scheduled_for,
        estimated_delivery_at=order.estimated_delivery_at,
        cancelled_by=str(order.cancelled_by) if order.cancelled_by else None,
        cancellation_reason=order.cancellation_reason,
        actions=_actions(order),
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _mark_refunded(order: Order, admin: User, reason: str, now: datetime) -> None:
    order.payment_status = "REFUNDED"
    order.refunded_at = now
    order.refunded_by = admin.id
    order.refund_reason = reason


async def cancel_order(
    db: AsyncSession, admin: User, order_id: uuid.UUID, reason: str
) -> AdminOrderDetail:
    """Cancel on anyone's behalf, up to the moment a rider collects.

    A paid order is refunded in the same transaction, as a vendor rejection
    is: cancelling someone's order and keeping their money is not a state the
    platform should be able to reach, even for a moment.
    """
    order = await _load(db, order_id, for_update=True)
    current = OrderStatus(str(order.status))
    if OrderStatus.CANCELLED not in ORDER_TRANSITIONS.get(current, set()):
        raise ConflictError(
            f"An order that is {current} cannot be cancelled",
            details=[
                "Only PENDING, PREPARING and READY orders can be cancelled — "
                "once a rider has collected the food it can only be delivered"
            ],
        )

    now = datetime.now(UTC)
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=current.value,
            to_status=OrderStatus.CANCELLED.value,
            actor=ActorType.ADMIN.value,
            actor_id=admin.id,
            note=reason,
        )
    )
    order.status = OrderStatus.CANCELLED.value
    order.cancelled_at = now
    order.cancelled_by = ActorType.ADMIN.value
    order.cancellation_reason = reason
    order.auto_decline_at = None
    order.updated_at = now
    refunded = str(order.payment_status) == "PAID"
    if refunded:
        _mark_refunded(order, admin, reason, now)
    await db.flush()
    await db.refresh(order, ["status_history"])

    log.info(
        "admin_order_cancelled", order_id=str(order.id), admin_id=str(admin.id), refunded=refunded
    )
    return await _detail(db, order)


async def refund_order(
    db: AsyncSession, admin: User, order_id: uuid.UUID, reason: str
) -> AdminOrderDetail:
    """Record that a paid order's money is owed back, whatever its status.

    Refunding does not cancel: a delivered order with a missing item is still
    a delivered order. Only PAID orders qualify — an unpaid COD order has
    taken nothing, and a REFUNDED one has already been given back.
    """
    order = await _load(db, order_id, for_update=True)
    payment_status = str(order.payment_status)
    if payment_status != "PAID":
        raise ConflictError(
            "Only a paid order can be refunded",
            details=[f"This order's payment is {payment_status.lower()}"],
        )
    now = datetime.now(UTC)
    _mark_refunded(order, admin, reason, now)
    order.updated_at = now
    await db.flush()

    log.info("admin_order_refunded", order_id=str(order.id), admin_id=str(admin.id))
    return await _detail(db, order)
