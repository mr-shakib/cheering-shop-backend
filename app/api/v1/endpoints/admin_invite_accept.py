"""Accepting an administrator invitation — [EXTENDED] public endpoints.

The Sign up for admin screen: the invitation link carries a token; the screen
reads the invitation to pre-fill the email, then submits name and password.
"""

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.core import rate_limit
from app.core.client import client_ip
from app.core.config import settings
from app.core.responses import ok
from app.schemas.requests import AdminInvitationAcceptRequest
from app.services import admin_invitation_service, auth_service, token_service

router = APIRouter(prefix="/auth/admin-invitations", tags=["Authentication"])


@router.get("/{token}", summary="Read an invitation [EXTENDED]")
async def preview(token: str, request: Request, db: DbSession):
    """**[EXTENDED]** — the email to pre-fill (read-only on the form). `404` for
    an unknown, used, revoked or expired token alike."""
    await rate_limit.hit(
        rate_limit.login_ip_key(client_ip(request)),
        limit=settings.LOGIN_IP_MAX_ATTEMPTS,
        window_seconds=settings.LOGIN_WINDOW_SECONDS,
    )
    return ok((await admin_invitation_service.preview(db, token)).model_dump())


@router.post("/accept", summary="Accept an invitation and sign in [EXTENDED]")
async def accept(body: AdminInvitationAcceptRequest, request: Request, db: DbSession):
    """**[EXTENDED]** — creates the ADMIN account with the invited email and
    signs it in: the response is the same `{tokens, user}` as `/auth/login`."""
    await rate_limit.hit(
        rate_limit.login_ip_key(client_ip(request)),
        limit=settings.LOGIN_IP_MAX_ATTEMPTS,
        window_seconds=settings.LOGIN_WINDOW_SECONDS,
    )
    user = await admin_invitation_service.accept(db, body)
    tokens = await token_service.issue_token_pair(
        db, user, user_agent=request.headers.get("user-agent"), ip_address=client_ip(request)
    )
    await db.commit()
    return ok({"tokens": tokens.model_dump(), "user": auth_service.to_profile(user).model_dump()})
