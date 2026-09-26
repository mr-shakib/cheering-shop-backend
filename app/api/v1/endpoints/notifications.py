"""The in-app notification inbox and push device registration — [EXTENDED].
Any signed-in user."""

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, Paginated
from app.core.responses import PageMeta, ok
from app.schemas.requests import DeviceRegisterRequest
from app.services import notifications

router = APIRouter(tags=["Notifications"])


@router.get("/notifications", summary="My notifications [EXTENDED]")
async def my_notifications(user: CurrentUser, db: DbSession, page: Paginated):
    """**[EXTENDED]** — newest first. `meta.unread` is the badge count."""
    items, total, unread = await notifications.inbox(db, user, page.limit, page.offset)
    meta = PageMeta(
        total=total,
        limit=page.limit,
        offset=page.offset,
        page=(page.offset // page.limit) + 1 if page.limit else 1,
        has_more=page.offset + len(items) < total,
    ).model_dump()
    meta["unread"] = unread
    return ok([i.model_dump() for i in items], meta)


@router.post("/notifications/read-all", summary="Mark every notification read [EXTENDED]")
async def read_all(user: CurrentUser, db: DbSession):
    marked = await notifications.mark_read(db, user, None)
    await db.commit()
    return ok({"marked_read": marked})


@router.post("/notifications/{notification_id}/read", summary="Mark one read [EXTENDED]")
async def read_one(notification_id: uuid.UUID, user: CurrentUser, db: DbSession):
    marked = await notifications.mark_read(db, user, notification_id)
    await db.commit()
    return ok({"marked_read": marked})


@router.post("/users/me/devices", summary="Register this device for push [EXTENDED]")
async def register_device(body: DeviceRegisterRequest, user: CurrentUser, db: DbSession):
    """**[EXTENDED]** — send the FCM token after sign-in and whenever Firebase
    rotates it. Idempotent."""
    device = await notifications.register_device(db, user, body)
    await db.commit()
    return ok(device.model_dump())


@router.delete("/users/me/devices/{fcm_token}", summary="Stop push to this device [EXTENDED]")
async def unregister_device(fcm_token: str, user: CurrentUser, db: DbSession):
    """**[EXTENDED]** — call on sign-out."""
    removed = await notifications.unregister_device(db, user, fcm_token)
    await db.commit()
    return ok({"unregistered": removed})
