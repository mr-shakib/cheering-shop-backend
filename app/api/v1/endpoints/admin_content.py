"""Admin console — uploads, app banners and reels [EXTENDED].

Files go straight to R2: ask `POST /admin/uploads/presigned-url` for a URL,
PUT the bytes to it, then send the returned `public_url` in a banner, reel or
vendor field.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import (
    AdminReelCreateRequest,
    BannerCreateRequest,
    BannerUpdateRequest,
    PresignedUrlRequest,
    ReelUpdateRequest,
)
from app.services import banners, reels, storage_service

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/uploads/presigned-url", summary="Upload a file from the console [EXTENDED]")
async def create_upload_url(body: PresignedUrlRequest, admin: AdminUser):
    """**[EXTENDED]** — like `POST /uploads/presigned-url`, but for everything
    the console manages: images (JPEG, PNG, WebP, GIF), PDF documents, reel
    videos (MP4, MOV, WebM) and Lottie animations (`application/json`).
    `file_type` is signed into the URL, so the PUT must send the same
    `Content-Type`."""
    result = storage_service.create_presigned_put(
        str(admin.id),
        body.file_type,
        body.file_name,
        extra_types=storage_service.ADMIN_EXTRA_TYPES,
    )
    return ok(result.model_dump())


# ---------------------------------------------------------------------------
# App banners
# ---------------------------------------------------------------------------


@router.get("/banners", summary="App banners [EXTENDED]")
async def list_banners(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status_filter: Annotated[
        str,
        Query(alias="status", description="LIVE, SCHEDULED, EXPIRED, INACTIVE or ALL (default)"),
    ] = "ALL",
    placement: Annotated[str | None, Query(description="e.g. HOME")] = None,
):
    """**[EXTENDED]** — every banner, by placement then display order, each with
    whether it is showing right now."""
    rows, total = await banners.admin_list(
        db, limit=page.limit, offset=page.offset, placement=placement, status=status_filter
    )
    return paginated(
        [b.model_dump() for b in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.post("/banners", status_code=status.HTTP_201_CREATED, summary="Add a banner [EXTENDED]")
async def create_banner(body: BannerCreateRequest, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — image, GIF or Lottie. `media_type` is inferred from the
    URL when omitted. Set `starts_at`/`ends_at` to schedule it."""
    banner = await banners.create(db, admin, body)
    await db.commit()
    return ok(banner.model_dump())


@router.get("/banners/{banner_id}", summary="One banner [EXTENDED]")
async def get_banner(banner_id: uuid.UUID, admin: AdminUser, db: DbSession):
    return ok((await banners.get(db, banner_id)).model_dump())


@router.patch("/banners/{banner_id}", summary="Edit a banner [EXTENDED]")
async def update_banner(
    banner_id: uuid.UUID, body: BannerUpdateRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — including `is_active: false` to take it down and
    `sort_order` to reorder."""
    banner = await banners.update(db, banner_id, body)
    await db.commit()
    return ok(banner.model_dump())


@router.delete("/banners/{banner_id}", summary="Delete a banner [EXTENDED]")
async def delete_banner(banner_id: uuid.UUID, admin: AdminUser, db: DbSession):
    await banners.delete(db, banner_id)
    await db.commit()
    return ok({"message": "Banner deleted", "banner_id": str(banner_id)})


# ---------------------------------------------------------------------------
# Reels
# ---------------------------------------------------------------------------


@router.get("/reels", summary="Every reel [EXTENDED]")
async def list_reels(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status_filter: Annotated[
        str, Query(alias="status", description="LIVE, HIDDEN or ALL (default)")
    ] = "ALL",
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """**[EXTENDED]** — newest first, hidden ones included."""
    rows, total = await reels.admin_list(
        db,
        limit=page.limit,
        offset=page.offset,
        restaurant_id=restaurant_id,
        status=status_filter,
    )
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.post("/reels", status_code=status.HTTP_201_CREATED, summary="Post a reel [EXTENDED]")
async def create_reel(body: AdminReelCreateRequest, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — for any restaurant; it goes straight into the feed."""
    reel = await reels.admin_create(db, admin, body)
    await db.commit()
    return ok(reel.model_dump())


@router.patch("/reels/{reel_id}", summary="Edit or hide a reel [EXTENDED]")
async def update_reel(
    reel_id: uuid.UUID, body: ReelUpdateRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — `is_hidden: true` takes it out of the feed without
    deleting it; the vendor still sees it, with `hidden_reason`."""
    reel = await reels.admin_update(db, reel_id, body)
    await db.commit()
    return ok(reel.model_dump())


@router.delete("/reels/{reel_id}", summary="Delete a reel [EXTENDED]")
async def delete_reel(reel_id: uuid.UUID, admin: AdminUser, db: DbSession):
    await reels.admin_delete(db, reel_id)
    await db.commit()
    return ok({"message": "Reel deleted", "reel_id": str(reel_id)})
