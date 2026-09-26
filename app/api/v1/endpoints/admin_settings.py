"""Admin console — Settings [EXTENDED]."""

from fastapi import APIRouter

from app.api.deps import AdminUser, DbSession
from app.core.responses import ok
from app.schemas.requests import PlatformSettingsUpdateRequest
from app.services import platform_settings

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/settings", summary="Platform configuration [EXTENDED]")
async def get_settings(admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — effective values. A field not set here shows the server
    default it falls back to, and is listed in `using_server_defaults`."""
    row = await platform_settings.get(db)
    await db.commit()
    return ok(platform_settings.to_out(row).model_dump())


@router.patch("/settings", summary="Change platform configuration [EXTENDED]")
async def update_settings(body: PlatformSettingsUpdateRequest, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — PATCH: omitted fields are left alone, and an explicit
    `null` hands a field back to the server default. Delivery fees and active
    surcharges apply to the next checkout; the per-type commission rates apply
    to vendors created from now on (existing vendors keep their rate)."""
    result = await platform_settings.update(db, admin, body)
    await db.commit()
    return ok(result.model_dump())
