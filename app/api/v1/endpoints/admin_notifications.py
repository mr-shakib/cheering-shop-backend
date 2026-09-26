"""Admin console — Notification [EXTENDED]."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import NotificationCampaignRequest
from app.services import notifications

router = APIRouter(prefix="/admin/notifications", tags=["Admin"])


@router.get("", summary="Notification campaigns [EXTENDED]")
async def list_campaigns(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status: Annotated[str | None, Query(description="SCHEDULED, SENT, FAILED or CANCELLED")] = None,
    audience: Annotated[str | None, Query(description="CUSTOMER, VENDOR, RIDER or ALL")] = None,
):
    """**[EXTENDED]** — newest first, with how many inboxes and devices each
    reached."""
    rows, total = await notifications.list_campaigns(
        db, limit=page.limit, offset=page.offset, status=status, audience=audience
    )
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Send or schedule [EXTENDED]")
async def create_campaign(body: NotificationCampaignRequest, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — without `scheduled_for` it is sent now: it lands in
    every recipient's inbox and is pushed to their devices (if push is
    configured) before this returns. With it, the worker sends it within a
    minute of that time."""
    campaign = await notifications.create(db, admin, body)
    await db.commit()
    return ok(campaign.model_dump())


@router.post("/{campaign_id}/cancel", summary="Cancel a scheduled notification [EXTENDED]")
async def cancel_campaign(campaign_id: uuid.UUID, admin: AdminUser, db: DbSession):
    campaign = await notifications.cancel(db, campaign_id)
    await db.commit()
    return ok(campaign.model_dump())
