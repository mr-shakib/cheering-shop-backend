"""Admin console — inviting administrators [EXTENDED]."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import AdminInvitationRequest
from app.services import admin_invitation_service

router = APIRouter(prefix="/admin/invitations", tags=["Admin"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Invite an administrator [EXTENDED]")
async def invite(body: AdminInvitationRequest, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — emails a one-time link (`ADMIN_INVITE_URL`) that opens
    the Sign up for admin screen. Re-inviting an address revokes its earlier
    pending invitation. `409` if the address already has an account."""
    invitation = await admin_invitation_service.invite(db, admin, body)
    await db.commit()
    return ok(invitation.model_dump())


@router.get("", summary="Invitations [EXTENDED]")
async def list_invitations(admin: AdminUser, db: DbSession, page: Paginated):
    """**[EXTENDED]** — newest first, each PENDING, ACCEPTED, EXPIRED or REVOKED."""
    rows, total = await admin_invitation_service.list_invitations(db, page.limit, page.offset)
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.post("/{invitation_id}/revoke", summary="Revoke an invitation [EXTENDED]")
async def revoke(invitation_id: uuid.UUID, admin: AdminUser, db: DbSession):
    invitation = await admin_invitation_service.revoke(db, invitation_id)
    await db.commit()
    return ok(invitation.model_dump())
