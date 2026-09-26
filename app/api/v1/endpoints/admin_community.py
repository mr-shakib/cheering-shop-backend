"""Admin console — Community moderation [EXTENDED].

Ban user is account blocking: `PATCH /admin/users/{author_id}/status`.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import CommunityRemoveRequest
from app.services import community

router = APIRouter(prefix="/admin/community", tags=["Admin"])


@router.get("/posts", summary="Community moderation queue [EXTENDED]")
async def moderation_queue(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status: Annotated[str, Query(description="LIVE (default), REPORTED, REMOVED or ALL")] = "LIVE",
    sort: Annotated[
        Literal["reports", "recent"], Query(description="Most reported first, or newest")
    ] = "reports",
    q: Annotated[str | None, Query(description="Post text or author name")] = None,
    author_id: Annotated[str | None, Query()] = None,
):
    """**[EXTENDED]** — each post with its report count and whether its author
    is already banned."""
    posts, total = await community.moderation_queue(
        db,
        limit=page.limit,
        offset=page.offset,
        status=status,
        sort=sort,
        q=q,
        author_id=author_id,
    )
    return paginated(
        [p.model_dump() for p in posts], total=total, limit=page.limit, offset=page.offset
    )


@router.post("/posts/{post_id}/remove", summary="Remove a post [EXTENDED]")
async def remove_post(
    post_id: uuid.UUID, body: CommunityRemoveRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — the Delete button. The post leaves every feed; it stays
    on record with who removed it and why."""
    post = await community.remove(db, admin, post_id, body.reason)
    await db.commit()
    return ok(post.model_dump())
