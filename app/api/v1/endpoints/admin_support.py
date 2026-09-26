"""Admin console — Support Ticket and Live Chat [EXTENDED]."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import PageMeta, ok
from app.schemas.requests import SupportMessageRequest, SupportTicketUpdateRequest
from app.services import support

router = APIRouter(prefix="/admin/support", tags=["Admin"])


@router.get("/tickets", summary="Support ticket queue [EXTENDED]")
async def list_tickets(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status: Annotated[
        str | None,
        Query(description="OPEN, PENDING, RESOLVED, CLOSED, or ACTIVE (open + pending)"),
    ] = None,
    priority: Annotated[str | None, Query(description="LOW, MEDIUM, HIGH or URGENT")] = None,
    type: Annotated[str | None, Query(description="e.g. RIDER_COMPLAINT, REFUND")] = None,
    q: Annotated[
        str | None, Query(description="Ticket number, subject, user name or phone")
    ] = None,
    unread: Annotated[bool, Query(description="Only tickets with unread messages")] = False,
):
    """**[EXTENDED]** — most recent activity first. `meta.counts` has the
    number per status for the filter chips and the header ("12 pending")."""
    rows, total = await support.admin_list(
        db,
        limit=page.limit,
        offset=page.offset,
        status=status,
        priority=priority,
        type=type,
        q=q,
        unread_only=unread,
    )
    meta = PageMeta(
        total=total,
        limit=page.limit,
        offset=page.offset,
        page=(page.offset // page.limit) + 1 if page.limit else 1,
        has_more=page.offset + len(rows) < total,
    ).model_dump()
    meta["counts"] = (await support.counts(db)).model_dump()
    return ok([r.model_dump() for r in rows], meta)


@router.get("/tickets/{ticket_id}", summary="A ticket: details, thread and history [EXTENDED]")
async def get_ticket(ticket_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — Ticket details, the conversation, and History (the
    EVENT messages). Opening it marks the user's messages as read."""
    ticket = await support.admin_get(db, ticket_id)
    await db.commit()
    return ok(ticket.model_dump())


@router.post("/tickets/{ticket_id}/messages", summary="Reply as support [EXTENDED]")
async def reply(ticket_id: uuid.UUID, body: SupportMessageRequest, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — an OPEN ticket becomes PENDING (waiting on the user).
    The first reply on an unassigned ticket assigns it to you."""
    ticket = await support.reply_as_staff(db, admin, ticket_id, body)
    await db.commit()
    return ok(ticket.model_dump())


@router.patch("/tickets/{ticket_id}", summary="Close, prioritise or assign [EXTENDED]")
async def update_ticket(
    ticket_id: uuid.UUID, body: SupportTicketUpdateRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — the Close button is `{"status": "CLOSED"}`. Every change
    is written to the ticket's history."""
    ticket = await support.admin_update(db, admin, ticket_id, body)
    await db.commit()
    return ok(ticket.model_dump())
