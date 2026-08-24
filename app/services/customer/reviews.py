"""Reviews and the masked call — spec #33, #45.

A review updates the restaurant's aggregate in the same transaction it is
written. `rating_avg`/`rating_count` are stored rather than derived because
every discovery listing sorts by them: recomputing an average over all reviews
on each of twenty cards is the difference between an index scan and twenty
aggregate queries.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.review import Review
from app.models.user import User
from app.schemas.customer import ReviewOut
from app.schemas.requests import ReviewCreateRequest


def _as_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValidationError(f"{what} is not a valid id") from exc


async def create_review(
    db: AsyncSession, user_id: uuid.UUID, order_id: str, body: ReviewCreateRequest
) -> ReviewOut:
    """Spec #33. One review per order, and only for a delivered one.

    "Only what you actually received" is the whole integrity story for ratings:
    without it, anyone could place and cancel orders to move a competitor's
    score. `reviews.order_id` is UNIQUE, so the second attempt is refused by
    the database even if this check were bypassed.
    """
    order = await db.scalar(
        select(Order).where(
            Order.id == _as_uuid(order_id, "order_id"), Order.customer_id == user_id
        )
    )
    if order is None:
        raise NotFoundError("Order not found")
    if str(order.status) != OrderStatus.DELIVERED.value:
        raise ConflictError(
            "You can review an order once it has been delivered",
            details=[f"This order is {str(order.status).lower()}."],
        )

    existing = await db.scalar(select(Review).where(Review.order_id == order.id))
    if existing is not None:
        raise ConflictError("You have already reviewed this order")

    review = Review(
        order_id=order.id,
        customer_id=user_id,
        restaurant_id=order.restaurant_id,
        rider_id=order.rider_id,
        restaurant_rating=body.restaurant_rating,
        rider_rating=body.rider_rating if order.rider_id else None,
        comment=body.comment,
    )
    db.add(review)
    await db.flush()

    # Recompute from the table rather than incrementing a running average:
    # an incremental update that runs twice, or runs against a stale count,
    # produces a rating that can never be reconciled back to the reviews.
    stats = await db.execute(
        select(func.avg(Review.restaurant_rating), func.count()).where(
            Review.restaurant_id == order.restaurant_id
        )
    )
    average, count = stats.one()
    restaurant = await db.get(Restaurant, order.restaurant_id)
    if restaurant is not None:
        restaurant.rating_avg = round(float(average or 0), 2)
        restaurant.rating_count = int(count or 0)
    await db.flush()

    return ReviewOut(
        id=str(review.id),
        order_id=str(order.id),
        restaurant_rating=review.restaurant_rating,
        rider_rating=review.rider_rating,
        comment=review.comment,
        created_at=review.created_at,
    )


async def masked_call(db: AsyncSession, user: User, order_id: str) -> dict:
    """Spec #45. Bridge the customer and whoever is serving the order.

    No telephony provider is connected, so this returns what it can prove and
    is explicit about what it cannot: `available: false` and the counterparty's
    name, never a raw phone number. Returning the real number "for now" is how
    a masking feature quietly becomes a privacy incident — the whole point is
    that neither party learns the other's number.
    """
    order = await db.scalar(select(Order).where(Order.id == _as_uuid(order_id, "order_id")))
    if order is None:
        raise NotFoundError("Order not found")

    is_customer = order.customer_id == user.id
    restaurant = await db.get(Restaurant, order.restaurant_id)
    is_vendor = restaurant is not None and restaurant.owner_id == user.id
    if not (is_customer or is_vendor or order.rider_id == user.id):
        raise NotFoundError("Order not found")

    if str(order.status) in {OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value}:
        raise ConflictError("This order is closed; calling is no longer available")

    counterparty = (
        (restaurant.name if restaurant is not None else "the restaurant")
        if is_customer
        else "the customer"
    )
    return {
        "available": False,
        "order_id": str(order.id),
        "counterparty": counterparty,
        "detail": "Masked calling is not configured on this server.",
    }


__all__ = ["create_review", "masked_call"]
