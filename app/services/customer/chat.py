"""Order chat — the Message screen.

**The order is the thread.** There is no thread table and no thread lifecycle
to manage: who may post is derived from who is party to the order, and the
channel closes when the order does. That is a safety property, not a
simplification — a permanent line to a stranger's device is exactly what a
delivery app should not leave lying around after the food arrives.

Access is resolved on every call rather than cached on a membership row,
because the rider on an order changes and a stale membership would outlive the
reason it was granted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.chat import OrderMessage
from app.models.enums import ActorType, OrderStatus
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.customer import ChatMessageOut, ChatMessageSent, ChatThread
from app.schemas.requests import ChatMessageRequest


def _as_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValidationError(f"{what} is not a valid id") from exc


async def _resolve_party(
    db: AsyncSession, user: User, order_id: str
) -> tuple[Order, str, Restaurant | None]:
    """Who is this caller on this order? Raises rather than guessing.

    Returns the actor role to stamp on their messages. An ADMIN is admitted for
    support, which is why the role is resolved rather than assumed from the
    user's own role field.
    """
    order = await db.scalar(select(Order).where(Order.id == _as_uuid(order_id, "order_id")))
    if order is None:
        raise NotFoundError("Order not found")

    restaurant = await db.get(Restaurant, order.restaurant_id)
    if order.customer_id == user.id:
        return order, ActorType.CUSTOMER.value, restaurant
    if restaurant is not None and restaurant.owner_id == user.id:
        return order, ActorType.VENDOR.value, restaurant
    if order.rider_id is not None and order.rider_id == user.id:
        return order, ActorType.RIDER.value, restaurant
    if str(user.role) == "ADMIN":
        return order, ActorType.ADMIN.value, restaurant
    # Same 404 as a missing order: telling a stranger that an order exists but
    # is not theirs is itself a disclosure.
    raise NotFoundError("Order not found")


def _closed_reason(order: Order) -> str | None:
    """None means the channel is open."""
    status = str(order.status)
    if status == OrderStatus.CANCELLED.value:
        return "This order was cancelled."
    if status == OrderStatus.DELIVERED.value:
        closes_at = (order.delivered_at or datetime.now(UTC)) + timedelta(
            hours=settings.CHAT_OPEN_AFTER_DELIVERY_HOURS
        )
        if datetime.now(UTC) > closes_at:
            return "This order was delivered; the chat has closed."
    return None


def _to_out(message: OrderMessage, *, viewer_role: str, sender_name: str) -> ChatMessageOut:
    return ChatMessageOut(
        id=str(message.id),
        order_id=str(message.order_id),
        sender_role=str(message.sender_role),
        sender_name=sender_name,
        body=message.body,
        created_at=message.created_at,
        read_at=message.read_at,
        is_mine=str(message.sender_role) == viewer_role,
    )


async def _names(db: AsyncSession, order: Order, restaurant: Restaurant | None) -> dict[str, str]:
    """Display name per role, resolved once for the whole thread."""
    names = {
        ActorType.VENDOR.value: restaurant.name if restaurant else "Restaurant",
        ActorType.ADMIN.value: "Support",
        ActorType.SYSTEM.value: "Cheering Shop",
    }
    customer = await db.get(User, order.customer_id)
    names[ActorType.CUSTOMER.value] = (customer.full_name if customer else None) or "Customer"
    if order.rider_id:
        rider = await db.get(User, order.rider_id)
        names[ActorType.RIDER.value] = (rider.full_name if rider else None) or "Rider"
    else:
        names[ActorType.RIDER.value] = "Rider"
    return names


async def get_thread(db: AsyncSession, user: User, order_id: str) -> ChatThread:
    """The Message screen's initial load.

    Opening the thread marks the counterparty's messages read, because that is
    what opening a chat means — a separate "mark read" call would be one the
    client could forget, leaving a badge that never clears.
    """
    order, role, restaurant = await _resolve_party(db, user, order_id)
    names = await _names(db, order, restaurant)

    rows = await db.scalars(
        select(OrderMessage)
        .where(OrderMessage.order_id == order.id)
        .order_by(OrderMessage.created_at)
    )
    messages = list(rows.all())

    await db.execute(
        update(OrderMessage)
        .where(
            OrderMessage.order_id == order.id,
            OrderMessage.sender_role != role,
            OrderMessage.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.flush()

    # The counterparty is whoever the viewer is talking TO: the rider once one
    # is assigned, the restaurant before that.
    other_role = (
        ActorType.RIDER.value
        if role == ActorType.CUSTOMER.value and order.rider_id
        else ActorType.VENDOR.value
        if role == ActorType.CUSTOMER.value
        else ActorType.CUSTOMER.value
    )
    closed = _closed_reason(order)
    return ChatThread(
        order_id=str(order.id),
        is_open=closed is None,
        closed_reason=closed,
        counterparty_name=names.get(other_role),
        counterparty_role=other_role,
        unread_count=0,
        messages=[
            _to_out(m, viewer_role=role, sender_name=names.get(str(m.sender_role), "Unknown"))
            for m in messages
        ],
    )


async def send_message(
    db: AsyncSession, user: User, order_id: str, body: ChatMessageRequest
) -> ChatMessageSent:
    """Post one message. Refused once the channel has closed with the order."""
    order, role, restaurant = await _resolve_party(db, user, order_id)
    closed = _closed_reason(order)
    if closed is not None:
        raise ConflictError(closed)

    text = body.body.strip()
    if not text:
        raise ValidationError("Message cannot be empty")
    if len(text) > settings.CHAT_MESSAGE_MAX_LENGTH:
        raise ValidationError(
            f"Message is too long (max {settings.CHAT_MESSAGE_MAX_LENGTH} characters)"
        )

    message = OrderMessage(
        order_id=order.id, sender_id=user.id, sender_role=role, body=text
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)

    names = await _names(db, order, restaurant)
    return ChatMessageSent(
        message=_to_out(message, viewer_role=role, sender_name=names.get(role, "You")),
        delivered_over_websocket=False,
    )


async def unread_count(db: AsyncSession, user: User, order_id: str) -> int:
    """Badge count. Backed by `ix_order_messages_unread`, a partial index."""
    order, role, _ = await _resolve_party(db, user, order_id)
    return int(
        await db.scalar(
            select(func.count())
            .select_from(OrderMessage)
            .where(
                OrderMessage.order_id == order.id,
                OrderMessage.sender_role != role,
                OrderMessage.read_at.is_(None),
            )
        )
        or 0
    )


__all__ = ["get_thread", "send_message", "unread_count"]
