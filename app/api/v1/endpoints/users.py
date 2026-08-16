"""Users & Security state — spec endpoints #9, #13, plus [EXTENDED] password."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.responses import ok
from app.schemas.requests import ChangePasswordRequest, ProfileUpdateRequest
from app.services import auth_service, token_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", summary="Get the current user [EXTENDED]")
async def get_me(user: CurrentUser):
    """**[EXTENDED]** — the spec has no "who am I" endpoint.

    A mobile client restoring a saved token needs to know who it belongs to
    before it can render anything. The alternative is decoding the JWT
    client-side, which cannot tell you whether the profile has since changed.
    """
    return ok(auth_service.to_profile(user).model_dump())


@router.get("/me/security", summary="Get 2FA & biometrics state")
async def get_security_state(user: CurrentUser, db: DbSession):
    """Spec #9. Returns `{is_biometrics_enabled, is_2fa_enabled}`."""
    state = await auth_service.get_security_state(db, user)
    return ok(state.model_dump())


@router.put("/me/profile", summary="Update profile")
async def update_profile(body: ProfileUpdateRequest, user: CurrentUser, db: DbSession):
    """Spec #13.

    PUT replaces the mutable profile entirely (spec §2), so omitting a field
    clears it. Email and phone are not editable here: changing an identifier
    has to re-verify it, which is a separate OTP flow.
    """
    updated = await auth_service.update_profile(db, user, body.full_name, body.avatar_url)
    await db.commit()
    return ok(auth_service.to_profile(updated).model_dump())


@router.post("/me/password", summary="Set or change password [EXTENDED]")
async def change_password(body: ChangePasswordRequest, user: CurrentUser, db: DbSession):
    """**[EXTENDED]** — the spec only offers password *reset* via OTP.

    A signed-in user changing their own password should not have to pretend they
    forgot it. Requires the current password when one exists, so a stolen access
    token cannot lock the real owner out.

    Every other session is revoked on success: a password change is exactly when
    you want an attacker's session terminated.
    """
    await auth_service.change_password(db, user, body.new_password, body.current_password)
    revoked = await token_service.revoke_all_for_user(db, user.id)
    await db.commit()
    return ok({"message": "Password updated", "sessions_revoked": revoked})
