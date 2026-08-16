"""Users & Security state — spec endpoints #9, #13, plus [EXTENDED] endpoints."""

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser, DbSession
from app.core.client import client_ip
from app.core.responses import ok
from app.schemas.requests import ChangePasswordRequest, ProfileUpdateRequest
from app.services import auth_service, token_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", summary="Get the current user [EXTENDED]")
async def get_me(user: CurrentUser):
    """**[EXTENDED]** — the spec has no "who am I" endpoint.

    A mobile client restoring a saved token needs to resolve who it belongs to
    before it can render anything. Decoding the JWT client-side cannot reveal
    whether the profile changed since the token was issued.
    """
    return ok(auth_service.to_profile(user).model_dump())


@router.get("/me/security", summary="Get 2FA & biometrics state")
async def get_security_state(user: CurrentUser, db: DbSession):
    """Spec #9. Returns `{is_2fa_enabled, is_biometrics_enabled, ...}`."""
    state = await auth_service.get_security_state(db, user)
    return ok(state.model_dump())


@router.put("/me/profile", summary="Update profile")
async def update_profile(body: ProfileUpdateRequest, user: CurrentUser, db: DbSession):
    """Spec #13.

    PUT replaces the mutable profile entirely, so omitting a field clears it.
    A phone number set here is stored **unverified** — capturing it is what
    matters for a rider to make contact; proving ownership is a separate flow.

    Returns 409 if the phone number already belongs to another account.
    """
    updated = await auth_service.update_profile(
        db, user, body.full_name, body.avatar_url, body.phone
    )
    await db.commit()
    return ok(auth_service.to_profile(updated).model_dump())


@router.post("/me/password", summary="Set or change password [EXTENDED]")
async def change_password(
    body: ChangePasswordRequest, user: CurrentUser, db: DbSession, request: Request
):
    """**[EXTENDED]** — the spec only offers password *reset* via OTP.

    Two distinct cases, deliberately handled differently:

    * **First-time set** (an OTP-only account choosing a password during
      registration). Nothing to verify against, and no other sessions exist —
      so nothing is revoked. Revoking here would sign the user out in the
      middle of registering.
    * **Change** (a password already exists). The current one is required, so a
      stolen access token cannot lock the owner out. Every session is then
      revoked — a password change is exactly when you want an attacker's
      session killed — and a **fresh token pair is returned** so the caller
      stays signed in while every other device is dropped.
    """
    is_first_time = user.password_hash is None
    await auth_service.change_password(db, user, body.new_password, body.current_password)

    if is_first_time:
        await db.commit()
        return ok({"message": "Password set", "sessions_revoked": 0, "tokens": None})

    revoked = await token_service.revoke_all_for_user(db, user.id)
    tokens = await token_service.issue_token_pair(
        db, user, user_agent=request.headers.get("user-agent"), ip_address=client_ip(request)
    )
    await db.commit()
    return ok(
        {
            "message": "Password updated",
            "sessions_revoked": revoked,
            "tokens": tokens.model_dump(),
        }
    )
