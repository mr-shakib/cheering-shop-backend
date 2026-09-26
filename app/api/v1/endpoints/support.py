"""Help & support — [EXTENDED]. Any signed-in customer, vendor or rider.

Attachments are uploaded first with `POST /uploads/presigned-url`, then sent
as `{url, name}`. Poll the open ticket every few seconds while its screen is
up; replies from support also set `unread` on the ticket list.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import SupportMessageRequest, SupportTicketCreateRequest
from app.services import support

router = APIRouter(prefix="/support", tags=["Support"])


@router.post("/tickets", status_code=status.HTTP_201_CREATED, summary="Open a ticket [EXTENDED]")
async def create_ticket(body: SupportTicketCreateRequest, user: CurrentUser, db: DbSession):
    """**[EXTENDED]** — the first message is part of the ticket. `order_id` must
    be an order you placed, delivered or cooked."""
    ticket = await support.create_ticket(db, user, body)
    await db.commit()
    return ok(ticket.model_dump())


@router.get("/tickets", summary="My tickets [EXTENDED]")
async def my_tickets(user: CurrentUser, db: DbSession, page: Paginated):
    """**[EXTENDED]** — most recent activity first."""
    rows, total = await support.list_mine(db, user, page.limit, page.offset)
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/tickets/{ticket_id}", summary="One ticket and its thread [EXTENDED]")
async def my_ticket(ticket_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """**[EXTENDED]** — opening it marks support's replies as read."""
    ticket = await support.get_mine(db, user, ticket_id)
    await db.commit()
    return ok(ticket.model_dump())


@router.post("/tickets/{ticket_id}/messages", summary="Reply on my ticket [EXTENDED]")
async def reply(
    ticket_id: uuid.UUID, body: SupportMessageRequest, user: CurrentUser, db: DbSession
):
    """**[EXTENDED]** — replying to a RESOLVED ticket reopens it; a CLOSED one
    is `409` (open a new ticket)."""
    ticket = await support.reply_as_user(db, user, ticket_id, body)
    await db.commit()
    return ok(ticket.model_dump())
