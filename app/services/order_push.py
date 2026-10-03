"""Push notifications for an order's lifecycle and its chat.

The WebSocket channels (`services.realtime`) reach a screen that is open; this
reaches a phone in a pocket. Each status change goes to whoever has to act on
it or is waiting on it, and nobody else:

| Status | Who | Why |
|---|---|---|
| PENDING (placed) | vendor | a new order to accept |
| PREPARING | customer | the kitchen said yes |
| READY | assigned rider | the food is waiting (unassigned riders get the offer push) |
| PICKED_UP | customer | the food is on its way |
| DELIVERED | customer | done, and a nudge to rate |
| CANCELLED | the other parties | depends on who cancelled: see `_cancelled` |

A chat message goes to every party on the order except its sender.

**Push only, no inbox row.** The order screen and the chat thread are the
record of these events; copying every status into the inbox would bury the
announcements it exists for. A push carries `data.order_id`, so tapping it
opens the order.

**Called after the commit, as a background task.** Each call opens its own
session (the request's is gone by then), never raises, and commits only to
deactivate tokens FCM reported dead. Running after the response keeps FCM's
round trip off the vendor's "Accept" tap.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import LOCAL_TZ
from app.core.database import SessionLocal
from app.core.money import to_major
from app.models.enums import ActorType, OrderStatus
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User, UserDevice
from app.services import push_service
from app.services.pricing import PRIORITY

log = structlog.get_logger()

ORDER_UPDATE = "order_update"
CHAT_MESSAGE = "chat_message"
_CHAT_PREVIEW = 140


@dataclass(frozen=True)
class Push:
    user_id: uuid.UUID
    title: str
    body: str


def _taka(minor: int) -> str:
    amount = to_major(minor)
    return f"৳{amount:.0f}" if amount == amount.to_integral_value() else f"৳{amount}"


def _when(order: Order) -> str:
    """"Sat 4 Oct, 12:30 PM" on the Dhaka wall clock."""
    assert order.scheduled_for is not None
    return f"{order.scheduled_for.astimezone(LOCAL_TZ):%a %-d %b, %-I:%M %p}"


def _with_reason(sentence: str, reason: str | None) -> str:
    return f"{sentence}: {reason}" if reason else f"{sentence}."


async def _name(db: AsyncSession, user_id: uuid.UUID | None, fallback: str) -> str:
    user = await db.get(User, user_id) if user_id else None
    return (user.full_name if user else None) or fallback


async def _cancelled(db: AsyncSession, order: Order, restaurant: Restaurant) -> list[Push]:
    """Whoever cancelled already knows; everyone else still holding the order
    is told. A customer cancels only while PENDING, so no rider is involved;
    a vendor's refusal matters only to the customer; support can cancel up to
    READY, when the kitchen has cooked and a rider may be on the way."""
    n, reason = order.order_number, order.cancellation_reason
    by = str(order.cancelled_by) if order.cancelled_by else ActorType.SYSTEM.value
    if by == ActorType.CUSTOMER.value:
        return [
            Push(
                restaurant.owner_id,
                f"Order #{n} cancelled",
                _with_reason("The customer cancelled it", reason),
            )
        ]
    customer = Push(
        order.customer_id,
        f"Order #{n} was declined" if by == ActorType.VENDOR.value else f"Order #{n} was cancelled",
        _with_reason(
            f"{restaurant.name} couldn't take your order"
            if by == ActorType.VENDOR.value
            else "Support cancelled your order",
            reason,
        ),
    )
    if by == ActorType.VENDOR.value:
        return [customer]
    pushes = [
        customer,
        Push(
            restaurant.owner_id,
            f"Order #{n} was cancelled",
            "Support cancelled it. Stop preparing it.",
        ),
    ]
    if order.rider_id:
        pushes.append(
            Push(
                order.rider_id,
                f"Order #{n} was cancelled",
                f"Don't pick it up from {restaurant.name}.",
            )
        )
    return pushes


async def plan_status(
    db: AsyncSession, order: Order, restaurant: Restaurant, status: str
) -> list[Push]:
    """Who hears about `status`, and what they read. Pure decision; sends
    nothing."""
    n = order.order_number
    if status == OrderStatus.PENDING:
        if order.scheduled_for is not None:
            title = f"New scheduled order #{n}"
            body = f"For {_when(order)} · {_taka(order.grand_total)}"
        else:
            title = f"New order #{n}"
            body = f"{_taka(order.grand_total)} · tap to accept"
        if order.delivery_type == PRIORITY:
            title = f"Priority · {title}"
        return [Push(restaurant.owner_id, title, body)]
    if status == OrderStatus.PREPARING:
        body = (
            f"{restaurant.name} confirmed order #{n} for {_when(order)}."
            if order.scheduled_for is not None
            else f"{restaurant.name} is preparing order #{n}."
        )
        return [Push(order.customer_id, "Order accepted", body)]
    if status == OrderStatus.READY:
        if order.rider_id is None:
            return []  # the "still needs a rider" offer push covers it
        return [Push(order.rider_id, f"Order #{n} is ready", f"Pick it up at {restaurant.name}.")]
    if status == OrderStatus.PICKED_UP:
        rider = await _name(db, order.rider_id, "Your rider")
        return [
            Push(
                order.customer_id,
                "Your order is on the way",
                f"{rider} picked up order #{n} from {restaurant.name}.",
            )
        ]
    if status == OrderStatus.DELIVERED:
        return [
            Push(
                order.customer_id,
                "Order delivered",
                f"Enjoy your meal from {restaurant.name}! Tap to rate it.",
            )
        ]
    if status == OrderStatus.CANCELLED:
        return await _cancelled(db, order, restaurant)
    return []


async def plan_chat(
    db: AsyncSession, order: Order, restaurant: Restaurant, sender_id: uuid.UUID, text: str
) -> list[Push]:
    """Everyone on the order but the sender. The title says who wrote, the way
    the thread labels them."""
    if sender_id == order.customer_id:
        sender = await _name(db, sender_id, "Customer")
    elif sender_id == restaurant.owner_id:
        sender = restaurant.name
    elif sender_id == order.rider_id:
        sender = f"{await _name(db, sender_id, 'Your rider')} (Rider)"
    else:
        sender = "Support"
    preview = text if len(text) <= _CHAT_PREVIEW else text[: _CHAT_PREVIEW - 1] + "…"
    parties = [order.customer_id, restaurant.owner_id, order.rider_id]
    return [
        Push(uid, f"{sender} · Order #{order.order_number}", preview)
        for uid in dict.fromkeys(parties)  # one each, in order, even if a role is doubled
        if uid is not None and uid != sender_id
    ]


async def _deliver(db: AsyncSession, pushes: list[Push], data: dict[str, str]) -> int:
    sent = 0
    for push in pushes:
        tokens = list(
            (
                await db.scalars(
                    select(UserDevice.fcm_token)
                    .join(User, User.id == UserDevice.user_id)
                    .where(
                        UserDevice.user_id == push.user_id,
                        UserDevice.is_active.is_(True),
                        User.is_active.is_(True),
                    )
                )
            ).all()
        )
        result = await push_service.send(db, tokens, push.title, push.body, data)
        sent += result.sent
    await db.commit()  # persists any tokens push deactivated
    return sent


async def _load(db: AsyncSession, order_id: str) -> tuple[Order, Restaurant] | None:
    row = (
        await db.execute(
            select(Order, Restaurant)
            .join(Restaurant, Restaurant.id == Order.restaurant_id)
            .where(Order.id == uuid.UUID(str(order_id)))
        )
    ).first()
    return (row[0], row[1]) if row else None


async def order_status(order_id: str, status: str) -> int:
    """Push the change of `order_id` to `status`. `status` is passed rather
    than re-read, so a quick accept-then-ready still sends both. Returns how
    many devices it reached; never raises."""
    if not push_service.enabled():
        return 0
    try:
        async with SessionLocal() as db:
            loaded = await _load(db, order_id)
            if loaded is None:
                return 0
            order, restaurant = loaded
            pushes = await plan_status(db, order, restaurant, str(status))
            data = {
                "type": ORDER_UPDATE,
                "order_id": str(order.id),
                "order_number": str(order.order_number),
                "status": str(status),
            }
            return await _deliver(db, pushes, data)
    except Exception as exc:  # pragma: no cover - best effort by design
        log.warning("order_push_failed", order_id=str(order_id), status=status, error=str(exc))
        return 0


async def chat_message(order_id: str, sender_id: str, text: str) -> int:
    """Push a chat message to the order's other parties. Never raises."""
    if not push_service.enabled():
        return 0
    try:
        async with SessionLocal() as db:
            loaded = await _load(db, order_id)
            if loaded is None:
                return 0
            order, restaurant = loaded
            pushes = await plan_chat(db, order, restaurant, uuid.UUID(str(sender_id)), text)
            data = {
                "type": CHAT_MESSAGE,
                "order_id": str(order.id),
                "order_number": str(order.order_number),
            }
            return await _deliver(db, pushes, data)
    except Exception as exc:  # pragma: no cover - best effort by design
        log.warning("chat_push_failed", order_id=str(order_id), error=str(exc))
        return 0


__all__ = [
    "CHAT_MESSAGE",
    "ORDER_UPDATE",
    "Push",
    "chat_message",
    "order_status",
    "plan_chat",
    "plan_status",
]
