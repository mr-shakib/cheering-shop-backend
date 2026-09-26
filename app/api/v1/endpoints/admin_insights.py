"""Admin console — Overview, Finance and the search bar [EXTENDED].

Read-only. Money counts DELIVERED orders only, grouped by UTC day.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.services import admin_insights_service

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/dashboard", summary="The Overview screen in one call [EXTENDED]")
async def dashboard(admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — the stat cards (today vs yesterday), the Live order
    card and the eight most recent orders. The chart is
    `GET /admin/analytics/revenue`."""
    return ok((await admin_insights_service.dashboard(db)).model_dump())


@router.get("/analytics/revenue", summary="Revenue chart [EXTENDED]")
async def revenue(
    admin: AdminUser,
    db: DbSession,
    range: Annotated[Literal["7d", "30d", "12m"], Query(description="The chart's toggle")] = "7d",
):
    """**[EXTENDED]** — GMV per day (7d, 30d) or per month (12m). Every bucket
    is present, zero-filled, with a ready-made axis label. Shared by Overview
    and Finance."""
    return ok((await admin_insights_service.revenue_series(db, range)).model_dump())


@router.get("/finance/summary", summary="Finance cards and service split [EXTENDED]")
async def finance_summary(
    admin: AdminUser,
    db: DbSession,
    days: Annotated[int, Query(ge=1, le=366, description="Window length, ending now")] = 30,
):
    """**[EXTENDED]** — GMV, net revenue, commission and delivery revenue for
    the window against the one before it, and GMV split by business type."""
    return ok((await admin_insights_service.finance_summary(db, days)).model_dump())


@router.get("/finance/transactions", summary="Transaction details [EXTENDED]")
async def finance_transactions(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    date_from: Annotated[date | None, Query(description="Delivered on or after")] = None,
    date_to: Annotated[date | None, Query(description="Delivered on or before")] = None,
    q: Annotated[
        str | None, Query(description="Order number, payment reference, vendor or customer")
    ] = None,
):
    """**[EXTENDED]** — delivered orders as payments, newest first."""
    rows, total = await admin_insights_service.list_transactions(
        db, limit=page.limit, offset=page.offset, date_from=date_from, date_to=date_to, q=q
    )
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/search", summary="Search orders, customers, vendors and riders [EXTENDED]")
async def search(
    admin: AdminUser,
    db: DbSession,
    q: Annotated[str, Query(min_length=2, max_length=100)],
):
    """**[EXTENDED]** — the top bar. Up to five hits per group; orders match
    by number (`ORD-48210`, `#48210` or `48210`)."""
    return ok((await admin_insights_service.search(db, q)).model_dump())
