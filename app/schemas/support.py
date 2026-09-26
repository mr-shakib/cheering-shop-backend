"""Support tickets and their conversation, as every audience sees them.

Customers, vendors and riders use the same shapes as the admin console, minus
the staff-only fields, so the Live Chat screen and the in-app help screen
render the same thread."""

from datetime import datetime

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    url: str
    name: str


class TicketParty(BaseModel):
    id: str
    full_name: str | None = None
    role: str
    phone: str | None = None
    avatar_url: str | None = None


class SupportMessageOut(BaseModel):
    id: str
    kind: str = Field(description="MESSAGE, or EVENT for history lines like 'Ticket closed'")
    sender_id: str | None = None
    sender_role: str | None = Field(default=None, description="ADMIN for support staff")
    sender_name: str | None = None
    body: str
    attachments: list[Attachment] = Field(default_factory=list)
    created_at: datetime


class SupportTicketOut(BaseModel):
    id: str
    ticket_number: int
    code: str = Field(description='"TCK-8800" — what support and the user quote')
    subject: str
    type: str
    priority: str
    status: str = Field(
        description="OPEN (waiting on support), PENDING (waiting on the user), RESOLVED, CLOSED"
    )
    order_id: str | None = None
    order_number: int | None = None
    user: TicketParty
    assigned_to: TicketParty | None = None
    unread: bool = Field(description="New messages for whoever is reading this")
    last_message_preview: str | None = None
    last_message_at: datetime
    created_at: datetime
    resolved_at: datetime | None = None
    closed_at: datetime | None = None


class SupportTicketDetail(SupportTicketOut):
    messages: list[SupportMessageOut] = Field(
        description="The whole thread, oldest first, events included"
    )


class SupportQueueCounts(BaseModel):
    open: int
    pending: int
    resolved: int
    closed: int
    unread: int = Field(description="Tickets with a message support has not read")
    urgent: int = Field(description="Open or pending tickets at URGENT priority")
