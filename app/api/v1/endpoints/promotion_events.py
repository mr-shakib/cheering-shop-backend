"""Ad impression and click tracking — [EXTENDED]. Public.

The customer app reports which promoted restaurant cards were shown and
tapped, batched. Browsing is public, so no sign-in is needed; batches are
capped and rate limited per source IP.
"""

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.core import rate_limit
from app.core.client import client_ip
from app.core.responses import ok
from app.schemas.requests import PromotionEventsRequest
from app.services import admin_ad_service

router = APIRouter(prefix="/promotions", tags=["Discovery"])

_EVENTS_PER_MINUTE = 60


@router.post("/events", summary="Report promoted-card impressions and clicks [EXTENDED]")
async def record_events(body: PromotionEventsRequest, request: Request, db: DbSession):
    """**[EXTENDED]** — send the restaurant ids of cards from the home feed's
    `promoted` row: `impressions` when shown, `clicks` when tapped. Up to 50 of
    each per call; send every few seconds, not per card."""
    await rate_limit.hit(
        f"rl:promo-events:{client_ip(request)}", limit=_EVENTS_PER_MINUTE, window_seconds=60
    )
    counted = await admin_ad_service.record_events(db, body)
    await db.commit()
    return ok(counted)
