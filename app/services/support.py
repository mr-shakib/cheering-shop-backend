"""Support tickets: opened by customers, vendors and riders; answered by staff.

Status is whose turn it is:

* **OPEN** — waiting on support. A new ticket, or the user just replied.
* **PENDING** — support replied; waiting on the user.
* **RESOLVED** — support considers it done. The user replying reopens it.
* **CLOSED** — final. Nobody can reply; a new problem is a new ticket.

History ("Ticket created", "Assigned to …", "Closed") is written as EVENT rows
in the same thread, so one ordered read renders the conversation and the
timeline together. The red dots are two flags on the ticket: `unread_by_staff`
is set when the user writes and cleared when staff open the ticket;
`unread_by_user` is the mirror image.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import UserRole
from app.models.order import Order
from app.models.support import (
    TICKET_PRIORITIES,
    TICKET_STATUSES,
    TICKET_TYPES,
    SupportMessage,
    SupportTicket,
)
from app.models.user import User
from app.schemas.requests import (
    SupportMessageRequest,
    SupportTicketCreateRequest,
    SupportTicketUpdateRequest,
)
from app.schemas.support import (
    Attachment,
    SupportMessageOut,
    SupportQueueCounts,
    SupportTicketDetail,
    SupportTicketOut,
    TicketParty,
)
from app.services.admin.common import like_pattern, parse_uuid

log = structlog.get_logger()

_LIVE = ("OPEN", "PENDING")


def _party(user: User | None) -> TicketParty | None:
    if user is None:
        return None
    return TicketParty(
        id=str(user.id),
        full_name=user.full_name,
        role=str(user.role),
        phone=user.phone,
        avatar_url=user.avatar_url,
    )


def _event(ticket: SupportTicket, actor: User | None, body: str) -> SupportMessage:
    return SupportMessage(
        ticket_id=ticket.id,
        kind="EVENT",
        sender_id=actor.id if actor else None,
        sender_role=str(actor.role) if actor else None,
        body=body,
        attachments=[],
        # App clock, not now(): now() is the transaction's start, so every row
        # written in one request would tie and the thread order would be luck.
        created_at=datetime.now(UTC),
    )


async def _users(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    rows = await db.scalars(select(User).where(User.id.in_(ids)))
    return {u.id: u for u in rows.all()}


async def _to_out(
    db: AsyncSession, tickets: list[SupportTicket], *, for_staff: bool
) -> list[SupportTicketOut]:
    if not tickets:
        return []
    users = await _users(
        db, {t.user_id for t in tickets} | {t.assigned_to for t in tickets if t.assigned_to}
    )
    order_ids = [t.order_id for t in tickets if t.order_id]
    numbers: dict[uuid.UUID, int] = {}
    if order_ids:
        rows = await db.execute(select(Order.id, Order.order_number).where(Order.id.in_(order_ids)))
        numbers = {order_id: number for order_id, number in rows.all()}
    # The newest MESSAGE per ticket, for the list preview.
    ranked = (
        select(
            SupportMessage.ticket_id,
            SupportMessage.body,
            func.row_number()
            .over(partition_by=SupportMessage.ticket_id, order_by=SupportMessage.created_at.desc())
            .label("rn"),
        )
        .where(
            SupportMessage.ticket_id.in_([t.id for t in tickets]), SupportMessage.kind == "MESSAGE"
        )
        .subquery()
    )
    latest = await db.execute(select(ranked.c.ticket_id, ranked.c.body).where(ranked.c.rn == 1))
    previews: dict[uuid.UUID, str] = {ticket_id: body for ticket_id, body in latest.all()}
    out = []
    for t in tickets:
        preview = previews.get(t.id)
        out.append(
            SupportTicketOut(
                id=str(t.id),
                ticket_number=t.ticket_number,
                code=f"TCK-{t.ticket_number}",
                subject=t.subject,
                type=t.type,
                priority=t.priority,
                status=t.status,
                order_id=str(t.order_id) if t.order_id else None,
                order_number=numbers.get(t.order_id) if t.order_id else None,
                user=_party(users.get(t.user_id))
                or TicketParty(id=str(t.user_id), role="CUSTOMER"),
                assigned_to=_party(users.get(t.assigned_to)) if t.assigned_to else None,
                unread=t.unread_by_staff if for_staff else t.unread_by_user,
                last_message_preview=preview[:140] if preview else None,
                last_message_at=t.last_message_at,
                created_at=t.created_at,
                resolved_at=t.resolved_at,
                closed_at=t.closed_at,
            )
        )
    return out


async def _detail(
    db: AsyncSession, ticket: SupportTicket, *, for_staff: bool
) -> SupportTicketDetail:
    [summary] = await _to_out(db, [ticket], for_staff=for_staff)
    messages = list(
        (
            await db.scalars(
                select(SupportMessage)
                .where(SupportMessage.ticket_id == ticket.id)
                .order_by(SupportMessage.created_at, SupportMessage.id)
            )
        ).all()
    )
    senders = await _users(db, {m.sender_id for m in messages if m.sender_id})
    return SupportTicketDetail(
        **summary.model_dump(),
        messages=[
            SupportMessageOut(
                id=str(m.id),
                kind=m.kind,
                sender_id=str(m.sender_id) if m.sender_id else None,
                sender_role=str(m.sender_role) if m.sender_role else None,
                sender_name=senders[m.sender_id].full_name if m.sender_id in senders else None,
                body=m.body,
                attachments=[Attachment(**a) for a in (m.attachments or [])],
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


async def _add_message(
    db: AsyncSession,
    ticket: SupportTicket,
    sender: User,
    body: SupportMessageRequest | SupportTicketCreateRequest,
    text: str,
) -> None:
    db.add(
        SupportMessage(
            ticket_id=ticket.id,
            kind="MESSAGE",
            sender_id=sender.id,
            sender_role=str(sender.role),
            body=text.strip(),
            attachments=[a.model_dump() for a in body.attachments],
            created_at=datetime.now(UTC),
        )
    )
    ticket.last_message_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# The user's side
# ---------------------------------------------------------------------------


async def create_ticket(
    db: AsyncSession, user: User, body: SupportTicketCreateRequest
) -> SupportTicketDetail:
    if str(user.role) == UserRole.ADMIN:
        raise ValidationError("Support staff reply to tickets; they do not open them")
    order_id = parse_uuid(body.order_id, "order_id")
    if order_id is not None:
        order = await db.get(Order, order_id)
        # Only an order the user took part in, and the same 404 either way.
        if (
            order is None
            or user.id not in {order.customer_id, order.rider_id}
            and not (str(user.role) == UserRole.VENDOR and await _owns_restaurant(db, user, order))
        ):
            raise NotFoundError("Order not found")

    ticket = SupportTicket(
        user_id=user.id, subject=body.subject.strip(), type=body.type, order_id=order_id
    )
    db.add(ticket)
    await db.flush()
    db.add(_event(ticket, user, "Ticket created"))
    await _add_message(db, ticket, user, body, body.message)
    await db.flush()
    await db.refresh(ticket)
    log.info("support_ticket_created", ticket_number=ticket.ticket_number, type=body.type)
    return await _detail(db, ticket, for_staff=False)


async def _owns_restaurant(db: AsyncSession, user: User, order: Order) -> bool:
    from app.models.restaurant import Restaurant

    restaurant = await db.get(Restaurant, order.restaurant_id)
    return restaurant is not None and restaurant.owner_id == user.id


async def _mine(
    db: AsyncSession, user: User, ticket_id: uuid.UUID, *, lock: bool = False
) -> SupportTicket:
    ticket = await db.get(SupportTicket, ticket_id, with_for_update=lock)
    if ticket is None or ticket.user_id != user.id:
        raise NotFoundError("Ticket not found")
    return ticket


async def list_mine(
    db: AsyncSession, user: User, limit: int, offset: int
) -> tuple[list[SupportTicketOut], int]:
    total = await db.scalar(
        select(func.count()).select_from(SupportTicket).where(SupportTicket.user_id == user.id)
    )
    rows = await db.scalars(
        select(SupportTicket)
        .where(SupportTicket.user_id == user.id)
        .order_by(SupportTicket.last_message_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return await _to_out(db, list(rows.all()), for_staff=False), int(total or 0)


async def get_mine(db: AsyncSession, user: User, ticket_id: uuid.UUID) -> SupportTicketDetail:
    ticket = await _mine(db, user, ticket_id)
    if ticket.unread_by_user:
        ticket.unread_by_user = False
        await db.flush()
    return await _detail(db, ticket, for_staff=False)


async def reply_as_user(
    db: AsyncSession, user: User, ticket_id: uuid.UUID, body: SupportMessageRequest
) -> SupportTicketDetail:
    ticket = await _mine(db, user, ticket_id, lock=True)
    if ticket.status == "CLOSED":
        raise ConflictError(
            "This ticket is closed", details=["Open a new ticket for a new problem"]
        )
    if ticket.status == "RESOLVED":
        db.add(_event(ticket, user, "Reopened by the user"))
        ticket.resolved_at = None
    await _add_message(db, ticket, user, body, body.body)
    ticket.status = "OPEN"
    ticket.unread_by_staff = True
    ticket.unread_by_user = False
    await db.flush()
    return await _detail(db, ticket, for_staff=False)


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------


async def admin_list(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    priority: str | None = None,
    type: str | None = None,
    q: str | None = None,
    unread_only: bool = False,
) -> tuple[list[SupportTicketOut], int]:
    """Most recent activity first. `status` also accepts ACTIVE (OPEN and
    PENDING) — the Live Chat list's default."""
    requester = aliased(User)
    conditions: list[ColumnElement[bool]] = []
    for raw, column, allowed in (
        (priority, SupportTicket.priority, TICKET_PRIORITIES),
        (type, SupportTicket.type, TICKET_TYPES),
    ):
        if raw:
            value = raw.strip().upper()
            if value not in allowed:
                raise ValidationError(f"Expected one of: {', '.join(allowed)}")
            conditions.append(column == value)
    if status:
        value = status.strip().upper()
        if value == "ACTIVE":
            conditions.append(SupportTicket.status.in_(_LIVE))
        elif value in TICKET_STATUSES:
            conditions.append(SupportTicket.status == value)
        else:
            raise ValidationError(f"status must be ACTIVE or one of: {', '.join(TICKET_STATUSES)}")
    if unread_only:
        conditions.append(SupportTicket.unread_by_staff.is_(True))
    if q and q.strip():
        pattern = like_pattern(q.strip())
        matches: list[ColumnElement[bool]] = [
            SupportTicket.subject.ilike(pattern),
            requester.full_name.ilike(pattern),
            requester.phone.ilike(pattern),
        ]
        digits = q.strip().upper().removeprefix("TCK-").removeprefix("#")
        if digits.isdigit() and len(digits) < 18:
            matches.append(SupportTicket.ticket_number == int(digits))
        conditions.append(or_(*matches))

    base = (
        select(SupportTicket)
        .join(requester, requester.id == SupportTicket.user_id)
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.order_by(SupportTicket.last_message_at.desc()).limit(limit).offset(offset)
    )
    return await _to_out(db, list(rows.all()), for_staff=True), int(total or 0)


async def counts(db: AsyncSession) -> SupportQueueCounts:
    row = (
        await db.execute(
            select(
                *(func.count().filter(SupportTicket.status == s) for s in TICKET_STATUSES),
                func.count().filter(SupportTicket.unread_by_staff.is_(True)),
                func.count().filter(
                    SupportTicket.status.in_(_LIVE), SupportTicket.priority == "URGENT"
                ),
            )
        )
    ).one()
    return SupportQueueCounts(
        open=row[0], pending=row[1], resolved=row[2], closed=row[3], unread=row[4], urgent=row[5]
    )


async def _any(db: AsyncSession, ticket_id: uuid.UUID, *, lock: bool = False) -> SupportTicket:
    ticket = await db.get(SupportTicket, ticket_id, with_for_update=lock)
    if ticket is None:
        raise NotFoundError("Ticket not found")
    return ticket


async def admin_get(db: AsyncSession, ticket_id: uuid.UUID) -> SupportTicketDetail:
    ticket = await _any(db, ticket_id)
    if ticket.unread_by_staff:
        ticket.unread_by_staff = False
        await db.flush()
    return await _detail(db, ticket, for_staff=True)


async def reply_as_staff(
    db: AsyncSession, admin: User, ticket_id: uuid.UUID, body: SupportMessageRequest
) -> SupportTicketDetail:
    ticket = await _any(db, ticket_id, lock=True)
    if ticket.status == "CLOSED":
        raise ConflictError("This ticket is closed")
    if ticket.assigned_to is None:
        ticket.assigned_to = admin.id
        db.add(_event(ticket, admin, f"Assigned to {admin.full_name or 'a support agent'}"))
    await _add_message(db, ticket, admin, body, body.body)
    if ticket.status == "OPEN":
        ticket.status = "PENDING"
    ticket.unread_by_user = True
    ticket.unread_by_staff = False
    await db.flush()
    return await _detail(db, ticket, for_staff=True)


async def admin_update(
    db: AsyncSession, admin: User, ticket_id: uuid.UUID, body: SupportTicketUpdateRequest
) -> SupportTicketDetail:
    ticket = await _any(db, ticket_id, lock=True)
    fields = body.model_fields_set
    now = datetime.now(UTC)

    if body.status is not None and body.status != ticket.status:
        if ticket.status == "CLOSED":
            raise ConflictError(
                "A closed ticket cannot be reopened; ask the user to open a new one"
            )
        ticket.status = body.status
        if body.status == "RESOLVED":
            ticket.resolved_at = now
        elif body.status in _LIVE:
            ticket.resolved_at = None
        ticket.closed_at = now if body.status == "CLOSED" else None
        ticket.unread_by_user = True
        db.add(_event(ticket, admin, f"Marked {body.status.lower()}"))
    if body.priority is not None and body.priority != ticket.priority:
        db.add(_event(ticket, admin, f"Priority set to {body.priority.lower()}"))
        ticket.priority = body.priority
    if "assigned_to" in fields and body.assigned_to != ticket.assigned_to:
        if body.assigned_to is None:
            db.add(_event(ticket, admin, "Unassigned"))
        else:
            agent = await db.get(User, body.assigned_to)
            if agent is None or str(agent.role) != UserRole.ADMIN:
                raise ValidationError("Tickets can only be assigned to an administrator")
            db.add(_event(ticket, admin, f"Assigned to {agent.full_name or agent.email}"))
        ticket.assigned_to = body.assigned_to
    await db.flush()
    log.info("support_ticket_updated", ticket_number=ticket.ticket_number, fields=sorted(fields))
    return await _detail(db, ticket, for_staff=True)
