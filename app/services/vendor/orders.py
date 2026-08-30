"""The vendor side of the order lifecycle: queue, transitions, handoff.

**The state machine is the product.** `ORDER_TRANSITIONS` in `app.models.enums`
is the single source of truth for what may follow what, and every mutation here
goes through `_transition`. The database will happily accept
PENDING -> DELIVERED; nothing in this module will.

Read-only numbers (analytics, dashboard, reviews, reports) live next door in
`app.services.vendor.insights` — this module is the one that changes state.

Decisions worth knowing before reading:

* **D3 (amended) — the handoff PIN is issued at READY, not at order
  creation.** It does not exist during the cooking window. HMAC'd for
  verification, and Fernet-encrypted so the vendor's handoff screen can
  re-display it while READY — see `mark_ready`.
* **D6 — earnings use the per-order `commission_amount` snapshot.** Never the
  live `restaurants.commission_rate`. Renegotiating a vendor's rate must not
  retroactively rewrite what they earned last month.
* **Rejection refunds, it does not rebook.** See `reject_order`.
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.errors import ConflictError, ErrorCode, NotFoundError, ValidationError
from app.core.money import to_major
from app.core.security import generate_rider_pin, hash_rider_pin, verify_rider_pin
from app.models.enums import ORDER_TRANSITIONS, ActorType, OrderStatus
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.vendor import (
    HandoffResult,
    VendorOrderDetail,
    VendorOrderItemAddOnOut,
    VendorOrderItemOut,
    VendorOrderSummary,
)
from app.services.rider import dispatch

log = structlog.get_logger()

# The working set a kitchen screen actually wants: everything still in play.
ACTIVE_STATUSES = (OrderStatus.PENDING, OrderStatus.PREPARING, OrderStatus.READY)

# The three tabs of the vendor Order screen — New · Preparing · Complete — as
# the status sets behind them. The tab name is what a client sends to
# `?status=`, so no client has to hard-code a status list, and the dashboard
# chips count exactly these groups.
#
# READY belongs under Preparing deliberately: the food is cooked but still in
# the kitchen, and the handoff code lives on that card. An order leaves the tab
# when a rider takes it, not when the timer stops.
QUEUE_TABS: dict[str, tuple[OrderStatus, ...]] = {
    "NEW": (OrderStatus.PENDING,),
    "PREPARING": (OrderStatus.PREPARING, OrderStatus.READY),
    "COMPLETE": (OrderStatus.PICKED_UP, OrderStatus.DELIVERED),
    "ACTIVE": ACTIVE_STATUSES,
}

# The chips above the queue, in the order the screen draws them.
CHIP_TABS = ("NEW", "PREPARING", "COMPLETE")

# What a vendor may still cancel. Once a rider has the food it is out of the
# kitchen's hands and cancellation becomes a support problem, not an API call.
VENDOR_CANCELLABLE = (OrderStatus.PENDING, OrderStatus.PREPARING)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


async def _get_order(
    db: AsyncSession, restaurant: Restaurant, order_id, *, with_items: bool = False
) -> Order:
    """Fetch one order, scoped to this restaurant.

    The `restaurant_id` predicate is the authorisation check. Another vendor's
    order id resolves to 404 rather than 403 — a vendor should not be able to
    confirm that an order exists at all.
    """
    stmt = select(Order).where(Order.id == order_id, Order.restaurant_id == restaurant.id)
    if with_items:
        stmt = stmt.options(selectinload(Order.items).selectinload(OrderItem.add_ons))
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found")
    return order


def _seconds_to_auto_decline(order: Order) -> int | None:
    """Countdown for the tablet, or None once the order is no longer pending."""
    if order.status != OrderStatus.PENDING or order.auto_decline_at is None:
        return None
    deadline = order.auto_decline_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return max(0, int((deadline - datetime.now(UTC)).total_seconds()))


def to_summary(order: Order, item_count: int = 0) -> VendorOrderSummary:
    return VendorOrderSummary(
        id=str(order.id),
        restaurant_id=str(order.restaurant_id),
        order_number=order.order_number,
        status=str(order.status),
        payment_method=str(order.payment_method),
        payment_status=str(order.payment_status),
        item_count=item_count,
        item_total=to_major(order.item_total),
        grand_total=to_major(order.grand_total),
        commission_amount=to_major(order.commission_amount),
        vendor_payout=to_major(order.item_total - order.commission_amount),
        placed_at=order.placed_at,
        accepted_at=order.accepted_at,
        ready_at=order.ready_at,
        picked_up_at=order.picked_up_at,
        delivered_at=order.delivered_at,
        cancelled_at=order.cancelled_at,
        auto_decline_at=order.auto_decline_at,
        seconds_to_auto_decline=_seconds_to_auto_decline(order),
    )


def to_detail(
    order: Order, customer: User | None, handoff_code: str | None = None
) -> VendorOrderDetail:
    """Requires `items` (and their `add_ons`) to be eagerly loaded."""
    items = [
        VendorOrderItemOut(
            id=str(line.id),
            menu_item_id=str(line.menu_item_id) if line.menu_item_id else None,
            item_name=line.item_name,
            variant_name=line.variant_name,
            quantity=line.quantity,
            unit_price=to_major(line.unit_price),
            add_ons_total=to_major(line.add_ons_total),
            line_total=to_major(line.line_total),
            notes=line.notes,
            add_ons=[
                VendorOrderItemAddOnOut(name=a.name, price=to_major(a.price)) for a in line.add_ons
            ],
        )
        for line in sorted(order.items, key=lambda i: i.item_name)
    ]
    return VendorOrderDetail(
        **to_summary(order, item_count=sum(line.quantity for line in order.items)).model_dump(),
        items=items,
        customer_name=customer.full_name if customer else None,
        # The order's own contact, not the account's. A customer ordering for
        # someone else puts the recipient's number on the order.
        customer_phone=order.delivery_contact_phone,
        delivery_address_text=order.delivery_address_text,
        special_instructions=order.special_instructions,
        cancellation_reason=order.cancellation_reason,
        cancelled_by=str(order.cancelled_by) if order.cancelled_by else None,
        rider_pin_issued=order.rider_pin_hash is not None,
        handoff_code=handoff_code,
    )


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


async def _transition(
    db: AsyncSession,
    order: Order,
    to_status: OrderStatus,
    actor: User,
    note: str | None = None,
) -> None:
    """Move an order, or refuse — and record that it happened either way.

    The history row is not bookkeeping for its own sake: it is what settles
    "the vendor says they marked it ready an hour ago" in a dispute, and it
    powers the customer's tracking timeline.
    """
    current = OrderStatus(str(order.status))
    allowed = ORDER_TRANSITIONS.get(current, set())
    if to_status not in allowed:
        raise ConflictError(
            f"An order that is {current} cannot become {to_status}",
            code=ErrorCode.CONFLICT,
            details=[f"Allowed from {current}: {', '.join(sorted(allowed)) or 'nothing'}"],
        )

    order.status = to_status.value
    order.updated_at = datetime.now(UTC)
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=current.value,
            to_status=to_status.value,
            actor=ActorType.VENDOR.value,
            actor_id=actor.id,
            note=note,
        )
    )


async def accept_order(
    db: AsyncSession, restaurant: Restaurant, order_id, actor: User
) -> VendorOrderSummary:
    """Spec #39. PENDING -> PREPARING.

    Clearing `auto_decline_at` is what cancels the queued timeout: the arq
    sweeper's partial index is
    ``WHERE status = 'PENDING' AND auto_decline_at IS NOT NULL``, so an accepted
    order stops being a candidate the moment either half stops being true. No
    task handle to track, and a worker restart cannot resurrect the timeout.
    """
    order = await _get_order(db, restaurant, order_id)
    await _transition(db, order, OrderStatus.PREPARING, actor)
    order.accepted_at = datetime.now(UTC)
    order.auto_decline_at = None
    await db.flush()

    # Dispatch here, not at READY: a rider needs the cooking window to travel to
    # the restaurant, which is the whole point of assigning before the food is
    # done. Best effort — see `dispatch.auto_assign` for why an empty rider pool
    # must not fail a vendor's accept.
    await dispatch.auto_assign(db, order)

    log.info("order_accepted", order_id=str(order.id), restaurant_id=str(restaurant.id))
    return to_summary(order)


async def reject_order(
    db: AsyncSession, restaurant: Restaurant, order_id, actor: User, reason: str | None
) -> VendorOrderSummary:
    """Spec #40. Cancel and refund.

    **Spec §12 Q3 left the rebooking policy open** — silently re-place the cart
    with a nearby vendor, or refund and let the customer choose? This implements
    refund-and-notify.

    Automatic rebooking is a matching problem with no correct answer available
    to a backend: the substitute restaurant has different prices, a different
    menu, and a different delivery time, so "the same order" cannot be recreated
    without deciding on the customer's behalf what they are willing to pay and
    wait for. Charging someone for food they did not choose is the worse failure
    mode. Discovery already gives the client everything it needs to offer
    alternatives, so the recovery flow belongs there.

    Refunds are marked, not executed — no payment gateway is wired up yet.
    `payment_status` becomes REFUNDED for money actually taken; an unpaid COD
    order stays PENDING because there is nothing to return.
    """
    order = await _get_order(db, restaurant, order_id)

    current = OrderStatus(str(order.status))
    if current not in VENDOR_CANCELLABLE:
        raise ConflictError(
            f"An order that is {current} can no longer be rejected",
            details=["A vendor may reject only while the order is PENDING or PREPARING"],
        )

    await _transition(db, order, OrderStatus.CANCELLED, actor, note=reason)
    now = datetime.now(UTC)
    order.cancelled_at = now
    order.cancelled_by = ActorType.VENDOR.value
    order.cancellation_reason = reason
    order.auto_decline_at = None
    if str(order.payment_status) == "PAID":
        order.payment_status = "REFUNDED"
    await db.flush()

    log.info(
        "order_rejected",
        order_id=str(order.id),
        restaurant_id=str(restaurant.id),
        reason=reason,
        refunded=str(order.payment_status) == "REFUNDED",
    )
    return to_summary(order)


async def mark_ready(
    db: AsyncSession, restaurant: Restaurant, order_id, actor: User
) -> tuple[VendorOrderSummary, str | None]:
    """Spec #41. PREPARING -> READY, and issue the handoff PIN (D3, amended).

    Returns `(summary, pin)` — and the pin now goes to the vendor. The
    original D3 posture (rider tells vendor the code, proving presence) cannot
    operate while no rider app exists to receive it, and the shipped handoff
    screen is explicit: "Hand this code to your rider … confirm once the code
    above matches theirs." So the vendor displays it, the rider's app will
    show the same code, and the vendor confirms on a match. When the rider app
    lands, flipping proof-of-presence back is one change: stop returning the
    code here and in the order detail — the HMAC verification underneath is
    unchanged either way.

    Stored twice on purpose: the HMAC is what `handoff_order` verifies; the
    Fernet ciphertext is what lets the detail endpoint re-display the code
    while READY (an app restart must not strand a pickup).

    **Calling this on an order that is already READY reissues the PIN.** That
    is the only way out of the attempt lockout: `handoff_order` kills a code
    after `HANDOFF_MAX_ATTEMPTS` wrong guesses and tells the vendor to mark the
    order ready again, so this has to answer. It deliberately does not go
    through `_transition` to do it — ORDER_TRANSITIONS has no READY -> READY
    edge, adding one would loosen the state machine for every other caller, and
    a self-transition would write a status-history row recording a change that
    did not happen. `ready_at` keeps its original value for the same reason:
    the food became ready once, and prep-time analytics should not be rewritten
    by a reissue.
    """
    order = await _get_order(db, restaurant, order_id)
    reissue = str(order.status) == OrderStatus.READY
    if not reissue:
        await _transition(db, order, OrderStatus.READY, actor)
        order.ready_at = datetime.now(UTC)
        # A rider may still be missing if nobody was on shift when the kitchen
        # accepted. Last chance to find one before the handoff has to refuse.
        await dispatch.auto_assign(db, order)

    pin = generate_rider_pin()
    order.rider_pin_hash = hash_rider_pin(pin, str(order.id))
    order.rider_pin_cipher = encrypt_secret(pin)
    order.rider_pin_issued_at = datetime.now(UTC)
    # Reset per issuance: a fresh secret deserves a fresh attempt budget, and
    # carrying a spent one over would lock out a legitimate rider.
    order.handoff_attempts = 0
    await db.flush()

    log.info(
        "handoff_pin_reissued" if reissue else "order_ready",
        order_id=str(order.id),
        restaurant_id=str(restaurant.id),
    )
    return to_summary(order), pin


async def handoff_order(
    db: AsyncSession, restaurant: Restaurant, order_id, actor: User, rider_pin: str
) -> HandoffResult:
    """Spec #42. READY -> PICKED_UP against a valid rider PIN.

    The comparison is constant-time, but that is not what makes this safe: 10,000
    candidates fall to brute force in seconds however the digest is compared.
    **The attempt counter is the actual control.** After
    `HANDOFF_MAX_ATTEMPTS` failures the PIN is dead and the vendor must mark the
    order ready again to issue a new one, which caps an attacker at that many
    guesses per issuance.

    Note the failure path still commits: an attempt that is not persisted is not
    a counter, and rolling back on a wrong guess would make the budget
    unenforceable.
    """
    order = await _get_order(db, restaurant, order_id)

    if str(order.status) != OrderStatus.READY:
        raise ConflictError(
            f"An order that is {order.status} cannot be handed over",
            details=["Mark the order READY first"],
        )
    if not order.rider_pin_hash:
        raise ConflictError("No handoff PIN has been issued for this order")
    if order.rider_id is None:
        # ck_orders_rider_required would reject the PICKED_UP write anyway; this
        # turns a constraint violation into an explanation.
        raise ConflictError(
            "No rider has been assigned to this order yet",
            details=["A handoff needs an assigned rider; wait for dispatch"],
        )
    if order.handoff_attempts >= settings.HANDOFF_MAX_ATTEMPTS:
        raise ConflictError(
            "Too many incorrect PIN attempts for this order",
            code=ErrorCode.INVALID_RIDER_PIN,
            details=["Mark the order ready again to issue a new PIN"],
        )

    if not verify_rider_pin(rider_pin, str(order.id), order.rider_pin_hash):
        order.handoff_attempts += 1
        remaining = max(0, settings.HANDOFF_MAX_ATTEMPTS - order.handoff_attempts)
        await db.flush()
        await db.commit()
        log.warning(
            "handoff_pin_rejected",
            order_id=str(order.id),
            attempts=order.handoff_attempts,
        )
        raise ValidationError(
            "Incorrect rider PIN",
            code=ErrorCode.INVALID_RIDER_PIN,
            details=[f"{remaining} attempt(s) remaining before the PIN is locked"],
        )

    await _transition(db, order, OrderStatus.PICKED_UP, actor)
    now = datetime.now(UTC)
    order.picked_up_at = now
    # Burned on success. A PIN that stays valid after the food has left is a
    # replayable credential for no benefit.
    order.rider_pin_hash = None
    await db.flush()

    log.info("order_handed_off", order_id=str(order.id), restaurant_id=str(restaurant.id))
    return HandoffResult(
        order_id=str(order.id),
        status=str(order.status),
        picked_up_at=now,
        message="Handoff confirmed. The order is now with the rider.",
    )


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


def parse_status_filter(raw: str | None) -> list[str] | None:
    """Translate `?status=` into a list of order statuses.

    Accepts a single value, a comma-separated list, or one of the Order
    screen's tabs — `NEW`, `PREPARING`, `COMPLETE` — plus `ACTIVE` for
    "everything still in play". Tabs resolve before raw statuses, so
    `?status=PREPARING` is the whole tab (PREPARING **and** READY) rather than
    a list that drops an order the moment the kitchen marks it ready. A client
    that wants one exact state can still name it, e.g. `?status=PICKED_UP`.
    """
    if not raw:
        return None
    wanted: list[str] = []
    for part in raw.split(","):
        token = part.strip().upper()
        if not token:
            continue
        if token in QUEUE_TABS:
            wanted.extend(s.value for s in QUEUE_TABS[token])
            continue
        if token not in OrderStatus.__members__:
            raise ValidationError(
                f"Unknown order status '{token}'",
                details=[
                    f"Expected one of: {', '.join(OrderStatus.__members__)}, "
                    f"or a tab: {', '.join(QUEUE_TABS)}"
                ],
            )
        wanted.append(token)
    return list(dict.fromkeys(wanted)) or None


async def list_orders(
    db: AsyncSession,
    restaurant: Restaurant,
    limit: int,
    offset: int,
    statuses: list[str] | None = None,
) -> tuple[list[VendorOrderSummary], int]:
    """Spec #37. Served by `ix_orders_vendor_queue (restaurant_id, status, placed_at DESC)`.

    Newest first. The index's column order is why the status filter is free
    rather than a scan, so filtered and unfiltered queue polls cost the same.
    """
    conditions = [Order.restaurant_id == restaurant.id]
    if statuses:
        conditions.append(Order.status.in_(statuses))

    total = await db.scalar(select(func.count()).select_from(Order).where(*conditions)) or 0
    result = await db.execute(
        select(Order)
        .where(*conditions)
        .order_by(Order.placed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    orders = list(result.scalars().all())
    if not orders:
        return [], total

    # One grouped query for the line counts rather than loading every line item
    # of every order just to sum them.
    counts_result = await db.execute(
        select(OrderItem.order_id, func.coalesce(func.sum(OrderItem.quantity), 0))
        .where(OrderItem.order_id.in_([o.id for o in orders]))
        .group_by(OrderItem.order_id)
    )
    counts = {row[0]: int(row[1]) for row in counts_result.all()}

    return [to_summary(o, counts.get(o.id, 0)) for o in orders], total


async def get_order_detail(db: AsyncSession, restaurant: Restaurant, order_id) -> VendorOrderDetail:
    """[EXTENDED] The kitchen view: line items, options, notes, address.

    Absent from the spec, which defines a queue and no way to read one of its
    rows — a vendor could see that an order existed but not what to cook.
    """
    order = await _get_order(db, restaurant, order_id, with_items=True)
    customer = await db.get(User, order.customer_id)

    # The handoff screen re-displays the code while the order is READY. Once
    # picked up (or if issuance predates the cipher column) there is nothing
    # to show, and nothing is decrypted.
    handoff_code = None
    if str(order.status) == OrderStatus.READY and order.rider_pin_cipher:
        handoff_code = decrypt_secret(order.rider_pin_cipher)
    return to_detail(order, customer, handoff_code)


