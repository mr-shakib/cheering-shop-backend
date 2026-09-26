"""Admin console — Advertisement [EXTENDED]."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import PageMeta, ok
from app.schemas.requests import AdCampaignUpdateRequest
from app.services import admin_ad_service

router = APIRouter(prefix="/admin/advertisements", tags=["Admin"])


@router.get("", summary="Vendor ad campaigns [EXTENDED]")
async def list_campaigns(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status: Annotated[str | None, Query(description="SCHEDULED, ACTIVE, PAUSED or ENDED")] = None,
    q: Annotated[str | None, Query(description="Vendor name or promo code")] = None,
    restaurant_id: Annotated[str | None, Query()] = None,
):
    """**[EXTENDED]** — every vendor promotion with budget, impressions,
    clicks, redemptions and revenue. `meta.active` is the header count
    ("7 active campaigns")."""
    rows, total, active = await admin_ad_service.list_campaigns(
        db, limit=page.limit, offset=page.offset, status=status, q=q, restaurant_id=restaurant_id
    )
    meta = PageMeta(
        total=total,
        limit=page.limit,
        offset=page.offset,
        page=(page.offset // page.limit) + 1 if page.limit else 1,
        has_more=page.offset + len(rows) < total,
    ).model_dump()
    meta["active"] = active
    return ok([r.model_dump() for r in rows], meta)


@router.patch("/{campaign_id}", summary="Pause, resume or end a campaign [EXTENDED]")
async def set_status(
    campaign_id: uuid.UUID, body: AdCampaignUpdateRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — `ENDED` is final. The vendor sees the same change in
    their Promotions screen."""
    campaign = await admin_ad_service.set_status(db, admin, campaign_id, body.status)
    await db.commit()
    return ok(campaign.model_dump())
