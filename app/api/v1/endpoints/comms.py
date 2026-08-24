"""Communications — reviews, masked calling and order chat.

Spec endpoints #34–35, plus the Message screen, which the spec never covered.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, CustomerUser, DbSession
from app.core.responses import ok
from app.schemas.requests import ChatMessageRequest, ReviewCreateRequest
from app.services import chat_service, realtime, review_service

router = APIRouter(prefix="/orders", tags=["Communications"])


@router.post("/{order_id}/call", summary="Masked proxy call")
async def initiate_call(order_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Spec #34. Customer, Vendor or Rider.

    Asks the CPaaS provider to bridge the two parties over a masked number, so
    neither ever sees the other's real phone number. **No provider is
    configured**, so this returns `available: false` with the counterparty's
    name — never a raw phone number. Handing back the real number "for now" is
    how a masking feature quietly becomes a privacy incident.
    """
    result = await review_service.masked_call(db, user, str(order_id))
    return ok(result)


@router.post(
    "/{order_id}/reviews", status_code=status.HTTP_201_CREATED, summary="Submit a review"
)
async def create_review(
    order_id: uuid.UUID, body: ReviewCreateRequest, user: CustomerUser, db: DbSession
):
    """Spec #35. One review per order (UNIQUE constraint), permitted only once
    the order is DELIVERED.

    "Only what you actually received" is the whole integrity story for ratings:
    without it, anyone could place and cancel orders to move a competitor's
    score. The restaurant's `rating_avg` is recomputed from the reviews table in
    the same transaction rather than incremented, so it can always be
    reconciled back to the rows it summarises.
    """
    review = await review_service.create_review(db, user.id, str(order_id), body)
    await db.commit()
    return ok(review.model_dump())


@router.get("/{order_id}/messages", summary="Order chat thread [EXTENDED]")
async def get_messages(order_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """**[EXTENDED]** — the Message screen.

    The order *is* the thread: who may read it is derived from who is party to
    the order, and it closes with the order. Opening the thread marks the
    counterparty's messages read, because that is what opening a chat means — a
    separate "mark read" call is one a client can forget, leaving a badge that
    never clears.
    """
    thread = await chat_service.get_thread(db, user, str(order_id))
    await db.commit()
    return ok(thread.model_dump())


@router.post(
    "/{order_id}/messages", status_code=status.HTTP_201_CREATED, summary="Send a message [EXTENDED]"
)
async def send_message(
    order_id: uuid.UUID, body: ChatMessageRequest, user: CurrentUser, db: DbSession
):
    """**[EXTENDED]** — post one message.

    Refused once the channel has closed with the order. A permanent line to a
    stranger's device after the food arrived is a safety problem rather than a
    feature, so chat closes a configurable window after delivery.
    """
    sent = await chat_service.send_message(db, user, str(order_id), body)
    await db.commit()
    # Best-effort live delivery; the REST response is the source of truth and
    # the client renders from it either way.
    sent.delivered_over_websocket = await realtime.publish(
        realtime.order_channel(str(order_id)),
        {"type": "chat.message", "message": sent.message.model_dump()},
    )
    return ok(sent.model_dump())
