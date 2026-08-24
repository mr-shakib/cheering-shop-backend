"""Order chat — the Message screen.

Not in the original spec. Scoped tightly on purpose: a channel per order,
between the customer and whoever is currently serving it, that closes with the
order. An open line to a stranger's device long after delivery is a safety
problem rather than a feature.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatMessageOut(BaseModel):
    """One bubble.

    `sender_role` rather than a raw user id decides which side of the thread it
    renders on, so the client needs no identity comparison — and we never ship
    the counterparty's user id to the other side.
    """

    id: str
    order_id: str
    sender_role: str
    sender_name: str
    body: str
    created_at: datetime
    read_at: datetime | None = None
    is_mine: bool = False


class ChatThread(BaseModel):
    """The Message screen's initial load."""

    order_id: str
    is_open: bool = Field(description="False once the channel has closed with the order")
    closed_reason: str | None = None
    counterparty_name: str | None = None
    counterparty_role: str | None = None
    counterparty_avatar_url: str | None = None
    unread_count: int = 0
    messages: list[ChatMessageOut] = Field(default_factory=list)


class ChatMessageSent(BaseModel):
    message: ChatMessageOut
    delivered_over_websocket: bool = False
