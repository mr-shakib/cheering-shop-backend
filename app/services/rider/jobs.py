"""[EXTENDED] The rider app's own screens: my jobs, one job, delivered.

This is the actor the specification names four times and never gives an
endpoint. Its absence was not cosmetic — `PICKED_UP -> DELIVERED` is the only
transition nothing could perform, so every order in the system stopped one step
short of done, and with it every number derived from a delivered order:
earnings, payouts, the acceptance rate, a customer's right to leave a review.

Two things here are deliberately the rider's and not the vendor's:

* **The handoff code.** `job_detail` returns it while the order is READY, which
  is decision D3 as originally written: the rider reads the code out and the
  vendor typing it back proves a real courier is standing at the counter. The
  vendor still sees it too, because the vendor app is shipping against that
  field today — removing it here would break a client mid-build. When they are
  ready, the flip is deleting the field from the two vendor responses, and the
  HMAC verification underneath does not change.
* **Marking delivered.** The rider is the only party present at the door.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.crypto import decrypt_secret
from app.core.errors import ConflictError, NotFoundError
from app.core.money import to_major
from app.models.enums import ActorType, OrderStatus, PaymentMethod, PaymentStatus
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.restaurant import Restaurant
from app.models.rider import RiderProfile
from app.models.user import User
from app.schemas.rider import DeliveryResult, RiderJobDetail, RiderJobSummary

log = structlog.get_logger()

# The rider's two tabs. ACTIVE is everything still in their hands; an order
# that was cancelled after assignment is neither — it is gone, and showing it
# under "completed" would credit a delivery that never happened.
JOB_TABS: dict[str, tuple[OrderStatus, ...]] = {
    "ACTIVE": (
        OrderStatus.PENDING,
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.PICKED_UP,
    ),
    "COMPLETE": (OrderStatus.DELIVERED,),
}


def _collect_on_delivery(order: Order):
    """Cash the rider takes at the door. COD is the only method that owes any."""
    if str(order.payment_method) != PaymentMethod.COD or str(
        order.payment_status
    ) == PaymentStatus.PAID:
        return to_major(0)
    return to_major(order.grand_total)


def _to_summary(order: Order, restaurant: Restaurant | None, item_count: int) -> RiderJobSummary:
    return RiderJobSummary(
        order_id=str(order.id),
        order_number=order.order_number,
        status=str(order.status),
        restaurant_name=restaurant.name if restaurant else "",
        restaurant_address=restaurant.address_line if restaurant else "",
        restaurant_latitude=restaurant.latitude if restaurant else 0.0,
        restaurant_longitude=restaurant.longitude if restaurant else 0.0,
        delivery_address_text=order.delivery_address_text,
        delivery_latitude=order.delivery_latitude,
        delivery_longitude=order.delivery_longitude,
        item_count=item_count,
        grand_total=to_major(order.grand_total),
        payment_method=str(order.payment_method),
        collect_on_delivery=_collect_on_delivery(order),
        placed_at=order.placed_at,
        ready_at=order.ready_at,
        picked_up_at=order.picked_up_at,
        delivered_at=order.delivered_at,
    )


async def _load_job(db: AsyncSession, rider_id: uuid.UUID, order_id: uuid.UUID) -> Order:
    """A job the caller is actually carrying, or a 404.

    Someone else's order is not found rather than forbidden: confirming an id
    exists tells an enumerating caller which orders are real.
    """
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.rider_id == rider_id)
        .options(selectinload(Order.items))
    )
    if order is None:
        raise NotFoundError("No order assigned to you with that id")
    return order


async def list_jobs(
    db: AsyncSession, rider_id: uuid.UUID, limit: int, offset: int, tab: str = "ACTIVE"
) -> tuple[list[RiderJobSummary], int]:
    """The rider's queue. ACTIVE first-in-first-out; COMPLETE newest first."""
    statuses = JOB_TABS.get(tab.upper())
    if statuses is None:
        raise ConflictError(
            f"Unknown tab {tab}", details=[f"Use one of: {', '.join(sorted(JOB_TABS))}"]
        )

    where = (Order.rider_id == rider_id, Order.status.in_([s.value for s in statuses]))
    total = await db.scalar(select(func.count()).select_from(Order).where(*where))

    order_by = Order.placed_at if tab.upper() == "ACTIVE" else Order.delivered_at.desc()
    orders = (
        (
            await db.execute(
                select(Order).where(*where).order_by(order_by).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    if not orders:
        return [], int(total or 0)

    restaurants = {
        r.id: r
        for r in (
            await db.execute(
                select(Restaurant).where(
                    Restaurant.id.in_({o.restaurant_id for o in orders})
                )
            )
        )
        .scalars()
        .all()
    }
    rows = await db.execute(
        select(OrderItem.order_id, func.count())
        .where(OrderItem.order_id.in_([o.id for o in orders]))
        .group_by(OrderItem.order_id)
    )
    counts: dict[uuid.UUID, int] = {order_id: n for order_id, n in rows.all()}
    return [
        _to_summary(o, restaurants.get(o.restaurant_id), counts.get(o.id, 0)) for o in orders
    ], int(total or 0)


async def job_detail(
    db: AsyncSession, rider_id: uuid.UUID, order_id: uuid.UUID
) -> RiderJobDetail:
    """One job, with the handoff code while the food is waiting at the counter.

    This is D3 as designed: the code lives on the rider's screen, so the vendor
    typing it back is evidence the rider is there. It disappears the moment the
    order is no longer READY — after pickup there is nothing left to prove.
    """
    order = await _load_job(db, rider_id, order_id)
    restaurant = await db.get(Restaurant, order.restaurant_id)
    customer = await db.get(User, order.customer_id)

    handoff_code = None
    if str(order.status) == OrderStatus.READY and order.rider_pin_cipher:
        handoff_code = decrypt_secret(order.rider_pin_cipher)

    summary = _to_summary(order, restaurant, len(order.items))
    return RiderJobDetail(
        **summary.model_dump(),
        restaurant_phone=restaurant.phone if restaurant else None,
        customer_name=customer.full_name if customer else None,
        customer_phone=order.delivery_contact_phone,
        special_instructions=order.special_instructions,
        handoff_code=handoff_code,
    )


async def _complete(
    db: AsyncSession, order: Order, *, actor: ActorType, actor_id: uuid.UUID
) -> DeliveryResult:
    """The delivery itself, shared by the rider and the operator fallback.

    Cash changes hands here. A COD order becomes PAID because the rider took
    the money — not a payment gateway pretending, but the one payment method
    this platform genuinely executes. Prepaid methods are left alone; marking
    them PAID on delivery would forge a capture that never happened.
    """
    current = OrderStatus(str(order.status))
    if current is not OrderStatus.PICKED_UP:
        raise ConflictError(
            f"An order that is {current} cannot be delivered",
            details=["Collect the order from the restaurant first"],
        )

    now = datetime.now(UTC)
    order.status = OrderStatus.DELIVERED.value
    # ck_orders_delivered: DELIVERED without a timestamp is rejected outright.
    order.delivered_at = now
    order.updated_at = now
    if str(order.payment_method) == PaymentMethod.COD:
        order.payment_status = PaymentStatus.PAID.value

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=current.value,
            to_status=OrderStatus.DELIVERED.value,
            actor=actor.value,
            actor_id=actor_id,
        )
    )

    profile = await db.get(RiderProfile, order.rider_id)
    if profile is not None:
        profile.total_deliveries += 1
    await db.flush()

    log.info(
        "order_delivered",
        order_id=str(order.id),
        rider_id=str(order.rider_id),
        confirmed_by=actor.value,
    )
    return DeliveryResult(
        order_id=str(order.id),
        status=str(order.status),
        delivered_at=now,
        payment_status=str(order.payment_status),
        total_deliveries=profile.total_deliveries if profile else 0,
        message="Delivered. The order is complete.",
    )


async def deliver(db: AsyncSession, rider: User, order_id: uuid.UUID) -> DeliveryResult:
    """PICKED_UP -> DELIVERED. The transition nothing in the system could make.

    Only the assigned rider can call it, and only on an order they are actually
    holding: a delivery marked by anyone else is an unverifiable claim about a
    doorstep they were not standing at. `_load_job` is what enforces that — it
    scopes the lookup to the caller, so somebody else's order is simply not
    found.
    """
    order = await _load_job(db, rider.id, order_id)
    return await _complete(db, order, actor=ActorType.RIDER, actor_id=rider.id)


async def deliver_as_admin(db: AsyncSession, admin: User, order_id: uuid.UUID) -> DeliveryResult:
    """The operator fallback: confirm a delivery the rider could not.

    Shares `_complete` with the rider path so the money and the counters behave
    identically, but records ADMIN as the actor. That distinction is the point:
    a delivery nobody was at the door for must not be indistinguishable in the
    audit trail from one a courier confirmed there.
    """
    order = await db.get(Order, order_id, options=[selectinload(Order.items)])
    if order is None:
        raise NotFoundError("No order with that id")
    if order.rider_id is None:
        raise ConflictError(
            "That order has no rider",
            details=["An order nobody collected cannot have been delivered"],
        )
    return await _complete(db, order, actor=ActorType.ADMIN, actor_id=admin.id)
