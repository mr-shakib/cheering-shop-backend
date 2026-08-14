"""Communications — spec endpoints #34–35."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, CustomerUser, DbSession
from app.core.errors import NotImplementedYetError
from app.schemas.requests import ReviewCreateRequest

router = APIRouter(prefix="/orders", tags=["Communications"])


@router.post("/{order_id}/call", summary="Masked proxy call")
async def initiate_call(order_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Spec #34. Customer or Rider.

    Asks the CPaaS provider to bridge the two parties over a masked number, so
    neither ever sees the other's real phone number.
    """
    raise NotImplementedYetError()


@router.post("/{order_id}/reviews", status_code=status.HTTP_201_CREATED, summary="Submit a review")
async def create_review(
    order_id: uuid.UUID, body: ReviewCreateRequest, user: CustomerUser, db: DbSession
):
    """Spec #35. One review per order (UNIQUE constraint), permitted only once
    the order is DELIVERED. Enqueues a rating_avg recompute for the restaurant."""
    raise NotImplementedYetError()
