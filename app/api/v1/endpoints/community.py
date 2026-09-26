"""Community — [EXTENDED]. Any signed-in customer, vendor or rider.

Short posts about food and places, with up to four images (uploaded first via
`POST /uploads/presigned-url`) and an optional restaurant tag.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import CommunityPostRequest, CommunityReportRequest
from app.services import community

router = APIRouter(prefix="/community", tags=["Community"])


@router.get("/posts", summary="The community feed [EXTENDED]")
async def feed(user: CurrentUser, db: DbSession, page: Paginated):
    """**[EXTENDED]** — newest first; removed posts never appear."""
    posts, total = await community.feed(db, user, page.limit, page.offset)
    return paginated(
        [p.model_dump() for p in posts], total=total, limit=page.limit, offset=page.offset
    )


@router.post("/posts", status_code=status.HTTP_201_CREATED, summary="Post [EXTENDED]")
async def create_post(body: CommunityPostRequest, user: CurrentUser, db: DbSession):
    post = await community.create_post(db, user, body)
    await db.commit()
    return ok(post.model_dump())


@router.delete("/posts/{post_id}", summary="Delete my post [EXTENDED]")
async def delete_post(post_id: uuid.UUID, user: CurrentUser, db: DbSession):
    await community.delete_own(db, user, post_id)
    await db.commit()
    return ok({"message": "Post deleted", "post_id": str(post_id)})


@router.post("/posts/{post_id}/report", summary="Report a post [EXTENDED]")
async def report_post(
    post_id: uuid.UUID, body: CommunityReportRequest, user: CurrentUser, db: DbSession
):
    """**[EXTENDED]** — once per user per post; reporting again changes nothing."""
    count = await community.report(db, user, post_id, body.reason)
    await db.commit()
    return ok({"reported": True, "post_id": str(post_id), "report_count": count})
