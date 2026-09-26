"""Community: short posts customers share, and their moderation.

Reports are one per user per post (the primary key), and `report_count` is
kept on the post so the moderation queue sorts without a join. Removal is
soft: the post leaves every feed but stays on record with who removed it and
why. Banning an author is account blocking — `PATCH /admin/users/{id}/status`
— which also stops them posting, because a blocked account cannot call the API.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.models.community import CommunityPost, CommunityReport
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.community import CommunityPostOut, ModeratedPostOut, PostAuthor, PostRestaurant
from app.schemas.requests import CommunityPostRequest
from app.services.admin.common import like_pattern, parse_uuid

log = structlog.get_logger()


async def _render(
    db: AsyncSession, posts: list[CommunityPost], viewer: User | None, *, moderated: bool
) -> list:
    if not posts:
        return []
    authors = {
        u.id: u
        for u in (
            await db.scalars(select(User).where(User.id.in_({p.author_id for p in posts})))
        ).all()
    }
    tagged = {p.restaurant_id for p in posts if p.restaurant_id}
    restaurants: dict[uuid.UUID, str] = {}
    if tagged:
        rows = await db.execute(
            select(Restaurant.id, Restaurant.name).where(Restaurant.id.in_(tagged))
        )
        restaurants = {rid: name for rid, name in rows.all()}
    reported: set[uuid.UUID] = set()
    if viewer is not None:
        reported = set(
            (
                await db.scalars(
                    select(CommunityReport.post_id).where(
                        CommunityReport.reporter_id == viewer.id,
                        CommunityReport.post_id.in_([p.id for p in posts]),
                    )
                )
            ).all()
        )
    out: list[CommunityPostOut] = []
    for p in posts:
        author = authors.get(p.author_id)
        base = CommunityPostOut(
            id=str(p.id),
            author=PostAuthor(
                id=str(p.author_id),
                full_name=author.full_name if author else None,
                avatar_url=author.avatar_url if author else None,
            ),
            body=p.body,
            image_urls=list(p.image_urls or []),
            restaurant=PostRestaurant(id=str(p.restaurant_id), name=restaurants[p.restaurant_id])
            if p.restaurant_id in restaurants
            else None,
            is_mine=viewer is not None and viewer.id == p.author_id,
            reported_by_me=p.id in reported,
            created_at=p.created_at,
        )
        if moderated:
            out.append(
                ModeratedPostOut(
                    **base.model_dump(),
                    report_count=p.report_count,
                    author_is_active=bool(author and author.is_active),
                    is_removed=p.removed_at is not None,
                    removed_at=p.removed_at,
                    removal_reason=p.removal_reason,
                )
            )
        else:
            out.append(base)
    return out


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


async def create_post(db: AsyncSession, user: User, body: CommunityPostRequest) -> CommunityPostOut:
    if str(user.role) == UserRole.ADMIN:
        raise ForbiddenError("Administrators moderate the community; they do not post in it")
    if body.restaurant_id is not None and await db.get(Restaurant, body.restaurant_id) is None:
        raise NotFoundError("Restaurant not found")
    post = CommunityPost(
        author_id=user.id,
        body=body.body.strip(),
        image_urls=list(body.image_urls),
        restaurant_id=body.restaurant_id,
    )
    db.add(post)
    await db.flush()
    await db.refresh(post)
    [out] = await _render(db, [post], user, moderated=False)
    return out


async def feed(
    db: AsyncSession, viewer: User, limit: int, offset: int
) -> tuple[list[CommunityPostOut], int]:
    live = CommunityPost.removed_at.is_(None)
    total = await db.scalar(select(func.count()).select_from(CommunityPost).where(live))
    posts = list(
        (
            await db.scalars(
                select(CommunityPost)
                .where(live)
                .order_by(CommunityPost.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return await _render(db, posts, viewer, moderated=False), int(total or 0)


async def _live_post(db: AsyncSession, post_id: uuid.UUID, *, lock: bool = False) -> CommunityPost:
    post = await db.get(CommunityPost, post_id, with_for_update=lock)
    if post is None or post.removed_at is not None:
        raise NotFoundError("Post not found")
    return post


async def delete_own(db: AsyncSession, user: User, post_id: uuid.UUID) -> None:
    post = await _live_post(db, post_id, lock=True)
    if post.author_id != user.id:
        raise NotFoundError("Post not found")
    post.removed_at = datetime.now(UTC)
    post.removed_by = user.id
    post.removal_reason = "Deleted by the author"
    await db.flush()


async def report(db: AsyncSession, user: User, post_id: uuid.UUID, reason: str | None) -> int:
    """Idempotent per user. Returns the post's report count."""
    post = await _live_post(db, post_id, lock=True)
    if post.author_id == user.id:
        raise ValidationError("You cannot report your own post")
    created = await db.scalar(
        pg_insert(CommunityReport)
        .values(post_id=post.id, reporter_id=user.id, reason=reason)
        .on_conflict_do_nothing(index_elements=["post_id", "reporter_id"])
        .returning(CommunityReport.post_id)
    )
    if created is not None:
        post.report_count += 1
        await db.flush()
    return post.report_count


# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------


async def moderation_queue(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str = "LIVE",
    sort: str = "reports",
    q: str | None = None,
    author_id: str | None = None,
) -> tuple[list[ModeratedPostOut], int]:
    """Most reported first by default — the posts that need a decision."""
    conditions: list[ColumnElement[bool]] = []
    wanted = status.strip().upper()
    if wanted == "LIVE":
        conditions.append(CommunityPost.removed_at.is_(None))
    elif wanted == "REMOVED":
        conditions.append(CommunityPost.removed_at.is_not(None))
    elif wanted == "REPORTED":
        conditions += [CommunityPost.removed_at.is_(None), CommunityPost.report_count > 0]
    elif wanted != "ALL":
        raise ValidationError("status must be LIVE, REPORTED, REMOVED or ALL")
    if sort not in {"reports", "recent"}:
        raise ValidationError("sort must be reports or recent")
    if (aid := parse_uuid(author_id, "author_id")) is not None:
        conditions.append(CommunityPost.author_id == aid)
    base = select(CommunityPost).join(User, User.id == CommunityPost.author_id)
    if q and q.strip():
        pattern = like_pattern(q.strip())
        conditions.append(or_(CommunityPost.body.ilike(pattern), User.full_name.ilike(pattern)))

    base = base.where(*conditions)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    order = (
        (CommunityPost.report_count.desc(), CommunityPost.created_at.desc())
        if sort == "reports"
        else (CommunityPost.created_at.desc(),)
    )
    posts = list((await db.scalars(base.order_by(*order).limit(limit).offset(offset))).all())
    return await _render(db, posts, None, moderated=True), int(total or 0)


async def remove(
    db: AsyncSession, admin: User, post_id: uuid.UUID, reason: str
) -> ModeratedPostOut:
    post = await _live_post(db, post_id, lock=True)
    post.removed_at = datetime.now(UTC)
    post.removed_by = admin.id
    post.removal_reason = reason
    await db.flush()
    log.info("community_post_removed", post_id=str(post.id), admin_id=str(admin.id))
    [out] = await _render(db, [post], None, moderated=True)
    return out
