"""Users & Security state — spec endpoints #9, #13."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotImplementedYetError
from app.core.responses import ok
from app.services import auth_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me/security", summary="Get 2FA & biometrics state")
async def get_security_state(user: CurrentUser, db: DbSession):
    """Spec #9. Returns `{is_biometrics_enabled, is_2fa_enabled}`."""
    state = await auth_service.get_security_state(db, user)
    return ok(state.model_dump())


@router.put("/me/profile", summary="Update profile")
async def update_profile(user: CurrentUser, db: DbSession):
    """Spec #13. PUT replaces the mutable profile fields entirely (spec §2)."""
    raise NotImplementedYetError()
