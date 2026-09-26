"""Administrator invitations."""

from datetime import datetime

from pydantic import BaseModel, Field


class AdminInvitationOut(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    status: str = Field(description="PENDING, ACCEPTED, EXPIRED or REVOKED")
    invited_by: str | None = None
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime
    debug_token: str | None = Field(
        default=None,
        description="Development only: the token the email carries. Never set in production.",
    )


class InvitationPreview(BaseModel):
    """What the Sign up for admin screen pre-fills."""

    email: str
    full_name: str | None = None
    expires_at: datetime
