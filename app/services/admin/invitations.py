"""Inviting administrators — the only way to make one without shell access.

An existing administrator invites an email address; the invitee follows the
emailed link, chooses a name and password, and is signed in as an ADMIN.

* The token is 32 random bytes; only its SHA-256 is stored, so reading the
  table is not enough to accept someone else's invitation.
* One use, and it expires (`ADMIN_INVITE_TTL_HOURS`). Re-inviting an address
  revokes whatever was still pending for it.
* An address that already has an account of any role cannot be invited: a
  role is fixed at creation, and silently turning a customer into an
  administrator is not something an email link should be able to do.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError
from app.models.enums import UserRole
from app.models.platform import AdminInvitation
from app.models.user import User
from app.schemas.admin import AdminInvitationOut, InvitationPreview
from app.schemas.requests import AdminInvitationAcceptRequest, AdminInvitationRequest
from app.services import email_service

log = structlog.get_logger()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _status(inv: AdminInvitation, now: datetime) -> str:
    if inv.accepted_at:
        return "ACCEPTED"
    if inv.revoked_at:
        return "REVOKED"
    return "EXPIRED" if inv.expires_at <= now else "PENDING"


def to_out(inv: AdminInvitation, token: str | None = None) -> AdminInvitationOut:
    return AdminInvitationOut(
        id=str(inv.id),
        email=inv.email,
        full_name=inv.full_name,
        status=_status(inv, datetime.now(UTC)),
        invited_by=str(inv.invited_by) if inv.invited_by else None,
        expires_at=inv.expires_at,
        accepted_at=inv.accepted_at,
        created_at=inv.created_at,
        debug_token=token if settings.expose_debug_secrets else None,
    )


async def invite(db: AsyncSession, admin: User, body: AdminInvitationRequest) -> AdminInvitationOut:
    email = body.email.strip().lower()
    if await db.scalar(select(func.count()).select_from(User).where(User.email == email)):
        raise ConflictError(
            "That email already has an account",
            details=["Administrators need an address nobody else is using"],
        )
    now = datetime.now(UTC)
    await db.execute(
        update(AdminInvitation)
        .where(
            AdminInvitation.email == email,
            AdminInvitation.accepted_at.is_(None),
            AdminInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = secrets.token_urlsafe(32)
    invitation = AdminInvitation(
        email=email,
        full_name=body.full_name,
        token_hash=_hash(token),
        invited_by=admin.id,
        expires_at=now + timedelta(hours=settings.ADMIN_INVITE_TTL_HOURS),
    )
    db.add(invitation)
    await db.flush()
    await db.refresh(invitation)

    link = settings.ADMIN_INVITE_URL.format(token=token)
    inviter = admin.full_name or admin.email or "An administrator"
    text = (
        f"{inviter} invited you to the {settings.EMAIL_FROM_NAME} admin console.\n\n"
        f"Accept the invitation and choose your password here:\n{link}\n\n"
        f"The link works once and expires in {settings.ADMIN_INVITE_TTL_HOURS} hours."
    )
    try:
        await email_service.send_email(
            email,
            f"You're invited to the {settings.EMAIL_FROM_NAME} admin console",
            "".join(f"<p>{line}</p>" for line in text.split("\n\n")).replace(
                link, f'<a href="{link}">{link}</a>'
            ),
            text,
        )
    except Exception as exc:
        log.error("admin_invitation_email_failed", error=str(exc))
    log.info("admin_invited", invitation_id=str(invitation.id), admin_id=str(admin.id))
    return to_out(invitation, token)


async def list_invitations(
    db: AsyncSession, limit: int, offset: int
) -> tuple[list[AdminInvitationOut], int]:
    total = await db.scalar(select(func.count()).select_from(AdminInvitation))
    rows = await db.scalars(
        select(AdminInvitation)
        .order_by(AdminInvitation.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_out(i) for i in rows.all()], int(total or 0)


async def revoke(db: AsyncSession, invitation_id: uuid.UUID) -> AdminInvitationOut:
    invitation = await db.get(AdminInvitation, invitation_id, with_for_update=True)
    if invitation is None:
        raise NotFoundError("Invitation not found")
    if _status(invitation, datetime.now(UTC)) != "PENDING":
        raise ConflictError("Only a pending invitation can be revoked")
    invitation.revoked_at = datetime.now(UTC)
    await db.flush()
    return to_out(invitation)


async def _usable(db: AsyncSession, token: str, *, lock: bool = False) -> AdminInvitation:
    """The same 404 for unknown, used, revoked and expired: the difference is
    not something to confirm to whoever is guessing tokens."""
    query = select(AdminInvitation).where(AdminInvitation.token_hash == _hash(token))
    if lock:
        query = query.with_for_update()
    invitation = await db.scalar(query)
    if invitation is None or _status(invitation, datetime.now(UTC)) != "PENDING":
        raise NotFoundError("This invitation is invalid or has expired")
    return invitation


async def preview(db: AsyncSession, token: str) -> InvitationPreview:
    invitation = await _usable(db, token)
    return InvitationPreview(
        email=invitation.email, full_name=invitation.full_name, expires_at=invitation.expires_at
    )


async def accept(db: AsyncSession, body: AdminInvitationAcceptRequest) -> User:
    from app.services.auth_service import set_password

    invitation = await _usable(db, body.token, lock=True)
    if await db.scalar(
        select(func.count()).select_from(User).where(User.email == invitation.email)
    ):
        raise ConflictError("That email already has an account")

    user = User(
        id=uuid.uuid4(),
        role=UserRole.ADMIN.value,
        email=invitation.email,
        full_name=body.full_name.strip(),
        is_email_verified=True,  # they followed a link sent to it
    )
    db.add(user)
    await db.flush()
    await set_password(db, user, body.password)
    invitation.accepted_at = datetime.now(UTC)
    invitation.accepted_user_id = user.id
    await db.flush()
    log.info("admin_invitation_accepted", invitation_id=str(invitation.id), user_id=str(user.id))
    return user
