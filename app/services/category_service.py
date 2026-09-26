"""Platform browse categories: name matching, counting, and curation.

The customer home screen shows a row of chips — Burger, Pizza, Biryani — and
every food app's first tap is one of them. This module is what makes a chip
exist and what decides who appears under it.

**Vendors never manage this table directly.** When a vendor creates a menu
section, `resolve()` matches its name to a platform category or creates one,
and the section's `category_id` is set. That is the whole vendor-facing
contract: name a section "Burgers" and your restaurant is under Burger.

**A category a vendor created is hidden until an administrator approves it.**
The home screen is the most valuable surface on the platform, and the
alternative lets anyone who signs up write to it. So `resolve()` creates the
row with `is_active` false and `reviewed_at` NULL, which is the review queue.
Nothing about the vendor's own menu waits on that: their section is live on
their page immediately, and the moment the category is approved every
restaurant that accumulated under it appears at once.

**Administrators curate the result.** Approve, image, pin order, hide, and —
the one that matters most — merge, because "Burger", "Burgers" and
"Hamburgers" will all be typed by someone, and the customer must see one chip.
Every merge teaches the survivor the loser's spelling (`aliases`), so the
duplicate cannot come back.

`reviewed_at` is a separate column rather than an inference from `is_active`,
because "hidden, nobody has looked" and "hidden, an administrator decided
that" need opposite handling. Any admin write marks the row reviewed, so
deliberately hiding something also takes it out of the queue for good.

Counting is deliberately strict. A category is shown to customers only when a
*visible* restaurant has an *active* section under it holding at least one
*live* item — a chip that opens onto an empty screen is worse than no chip.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import and_, any_, case, distinct, exists, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.category import Category
from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant
from app.schemas.categories import CategoryAdminOut, PlatformCategoryRef
from app.schemas.requests import (
    CategoryCreateRequest,
    CategoryMergeRequest,
    CategoryUpdateRequest,
)

log = structlog.get_logger()

# A restaurant exists to customers when the vendor is verified AND has not
# deactivated the storefront. OPEN/CLOSED is separate and hides nothing.
# Discovery shares this predicate rather than restating it.
VISIBLE_RESTAURANT = and_(Restaurant.is_verified.is_(True), Restaurant.is_active.is_(True))


# ---------------------------------------------------------------------------
# Names
#
# Three derived forms of a name, each with one job:
#   match_key    — what two spellings are compared on ("Burgers " == "burgers")
#   slug_for     — the public identifier in URLs; stable once assigned
#   display_name — how an auto-created category is shown ("burger" → "Burger")
#
# Migration 0007 carries a snapshot of the first two for its backfill. Changing
# them here does not change what that migration did, by design.
# ---------------------------------------------------------------------------


def match_key(name: str) -> str:
    """Lower-cased and single-spaced: what aliases store and matching uses."""
    return " ".join(name.split()).lower()


def slug_for(name: str) -> str:
    """URL-safe identifier. NFKD first so "Café" degrades to "cafe" rather
    than to nothing; non-Latin names (বার্গার) keep nothing after that, so
    they get a stable hash instead of an empty slug the CHECK would refuse."""
    normalised = unicodedata.normalize("NFKD", " ".join(name.split()))
    ascii_only = normalised.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")[:100].strip("-")
    if slug:
        return slug
    return "c-" + hashlib.sha1(match_key(name).encode()).hexdigest()[:12]


def display_name(name: str) -> str:
    """Capitalise words the vendor typed in lower case; leave "BBQ" alone."""
    words = " ".join(name.split()).split(" ")
    return " ".join(w if any(c.isupper() for c in w) else w[:1].upper() + w[1:] for w in words)[:80]


def _as_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{what} is not a valid id") from exc


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def to_ref(category: Category) -> PlatformCategoryRef:
    return PlatformCategoryRef(
        id=str(category.id),
        name=category.name,
        slug=category.slug,
        image_url=category.image_url,
    )


def to_admin_out(
    category: Category, restaurant_count: int, section_count: int, product_count: int = 0
) -> CategoryAdminOut:
    return CategoryAdminOut(
        **to_ref(category).model_dump(),
        sort_order=category.sort_order,
        aliases=list(category.aliases or []),
        is_active=category.is_active,
        reviewed_at=category.reviewed_at,
        is_pending=category.reviewed_at is None,
        restaurant_count=restaurant_count,
        section_count=section_count,
        product_count=product_count,
        commission_rate=(
            float(category.commission_rate) if category.commission_rate is not None else None
        ),
        kind=category.kind,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


# ---------------------------------------------------------------------------
# Counting — the one definition of "sells under"
# ---------------------------------------------------------------------------


def _section_has_live_item():
    """Correlated to the enclosing MenuCategory: it holds an undeleted item.

    `is_available` is deliberately not required. Sold-out flickers dozens of
    times a service; a chip that appeared and vanished with it would look
    broken, and a sold-out dish is still a true answer to "who sells burgers".
    """
    return exists().where(
        MenuItem.category_id == MenuCategory.id,
        MenuItem.deleted_at.is_(None),
        MenuItem.is_hidden.is_(False),
    )


def restaurant_counts():
    """Subquery `(category_id, restaurant_count)`.

    One visible restaurant counts once however many of its sections link to
    the category — "Beef Burgers" and "Chicken Burgers" are one burger place.
    """
    return (
        select(
            MenuCategory.category_id.label("category_id"),
            func.count(distinct(MenuCategory.restaurant_id)).label("restaurant_count"),
        )
        .join(Restaurant, Restaurant.id == MenuCategory.restaurant_id)
        .where(
            VISIBLE_RESTAURANT,
            MenuCategory.is_active.is_(True),
            MenuCategory.category_id.is_not(None),
            _section_has_live_item(),
        )
        .group_by(MenuCategory.category_id)
        .subquery()
    )


def by_slug(slug: str):
    """Predicate: the category this public slug refers to.

    A merged-away category leaves its slug behind as an alias of the survivor,
    so a link shared before the merge still opens the right chip.
    """
    return or_(Category.slug == slug, literal(slug) == any_(Category.aliases))


def sells_under(slug: str):
    """EXISTS predicate on `Restaurant`: has a live section under this slug.

    The same rule as `restaurant_counts`, so `GET /restaurants?category=x`
    returns exactly the restaurants the chip's count promised.
    """
    return (
        select(1)
        .select_from(MenuCategory)
        .join(Category, Category.id == MenuCategory.category_id)
        .where(
            MenuCategory.restaurant_id == Restaurant.id,
            MenuCategory.is_active.is_(True),
            by_slug(slug),
            Category.is_active.is_(True),
            _section_has_live_item(),
        )
        .exists()
    )


# ---------------------------------------------------------------------------
# Resolution — the vendor path
# ---------------------------------------------------------------------------


async def find_by_name(db: AsyncSession, name: str) -> Category | None:
    """The category a section name belongs to, if one exists.

    Slug match first (the stable id), then the display name, then aliases.
    The slug is also tried against aliases: a merged-away category leaves its
    slug behind as an alias, so a name that used to resolve there still does.
    """
    slug, key = slug_for(name), match_key(name)
    stmt = (
        select(Category)
        .where(
            or_(
                Category.slug == slug,
                func.lower(Category.name) == key,
                literal(key) == any_(Category.aliases),
                literal(slug) == any_(Category.aliases),
            )
        )
        .order_by(
            case((Category.slug == slug, 0), (func.lower(Category.name) == key, 1), else_=2),
            Category.created_at,
        )
        .limit(1)
    )
    return await db.scalar(stmt)


async def resolve(db: AsyncSession, name: str) -> Category:
    """Find the category for a section name, or create it — hidden.

    A created category is `is_active=False` with `reviewed_at` NULL: linked to
    the vendor's section, invisible to customers, and sitting in the
    administrator's review queue. Matching an EXISTING category, hidden or
    not, is unaffected — this only governs what a brand-new name produces.

    Creation goes through `ON CONFLICT DO NOTHING` rather than a check-then-
    insert: two vendors saving a "Tacos" section in the same second would
    otherwise both find nothing, both insert, and one of them would get a 500
    for a category that now exists.
    """
    found = await find_by_name(db, name)
    if found is not None:
        return found

    slug = slug_for(name)
    inserted = await db.scalar(
        pg_insert(Category)
        .values(name=display_name(name), slug=slug, is_active=False)
        .on_conflict_do_nothing(index_elements=["slug"])
        .returning(Category.id)
    )
    if inserted is None:
        # Lost the race; the winner's row is what we wanted anyway.
        winner = await db.scalar(select(Category).where(Category.slug == slug))
        if winner is None:  # pragma: no cover - cannot happen without a concurrent delete
            raise ConflictError("Category could not be created")
        return winner

    category = await db.get(Category, inserted)
    assert category is not None
    log.info(
        "platform_category_created",
        category_id=str(category.id),
        slug=slug,
        by="vendor",
        pending_review=True,
    )
    return category


async def get_by_id(db: AsyncSession, category_id: uuid.UUID) -> Category | None:
    return await db.get(Category, category_id)


async def get_active(db: AsyncSession, category_id: uuid.UUID) -> Category:
    """A category a vendor may pin a section to. Hidden ones read as absent:
    the picker never offered them, so an id for one is a stale client."""
    category = await db.get(Category, category_id)
    if category is None or not category.is_active:
        raise NotFoundError("Platform category not found")
    return category


# ---------------------------------------------------------------------------
# Curation — the administrator path
# ---------------------------------------------------------------------------


async def _get(db: AsyncSession, category_id: uuid.UUID) -> Category:
    category = await db.get(Category, category_id)
    if category is None:
        raise NotFoundError("Category not found")
    return category


async def _claimed(
    db: AsyncSession, keys: set[str], slugs: set[str], exclude: uuid.UUID | None = None
) -> Category | None:
    """Another category already answering to any of these names."""
    if not keys and not slugs:
        return None
    conditions = []
    if slugs:
        conditions.append(Category.slug.in_(slugs))
    if keys:
        conditions.append(func.lower(Category.name).in_(keys))
        conditions.append(Category.aliases.overlap(list(keys)))
    stmt = select(Category).where(or_(*conditions))
    if exclude is not None:
        stmt = stmt.where(Category.id != exclude)
    return await db.scalar(stmt.limit(1))


def product_counts():
    """Live (undeleted) products per browse category, hidden ones included —
    an admin count, not a customer one."""
    return (
        select(MenuCategory.category_id.label("category_id"), func.count().label("n"))
        .join(MenuItem, MenuItem.category_id == MenuCategory.id)
        .where(MenuCategory.category_id.is_not(None), MenuItem.deleted_at.is_(None))
        .group_by(MenuCategory.category_id)
        .subquery()
    )


async def _counts_for(db: AsyncSession, category_id: uuid.UUID) -> tuple[int, int, int]:
    counts = restaurant_counts()
    restaurants = await db.scalar(
        select(counts.c.restaurant_count).where(counts.c.category_id == category_id)
    )
    sections = await db.scalar(
        select(func.count())
        .select_from(MenuCategory)
        .where(MenuCategory.category_id == category_id)
    )
    products = product_counts()
    product_count = await db.scalar(
        select(products.c.n).where(products.c.category_id == category_id)
    )
    return int(restaurants or 0), int(sections or 0), int(product_count or 0)


async def admin_get(db: AsyncSession, category_id: uuid.UUID) -> CategoryAdminOut:
    category = await _get(db, category_id)
    return to_admin_out(category, *await _counts_for(db, category.id))


async def admin_list(
    db: AsyncSession,
    limit: int,
    offset: int,
    *,
    pending_only: bool = False,
    q: str | None = None,
    kind: str | None = None,
    sort: str = "default",
) -> tuple[list[CategoryAdminOut], int]:
    """Everything, hidden and empty included — this is the curation screen.

    Same order the customer sees (pinned, then popular) so what an operator
    drags to the top is what the app shows at the top. With `pending_only`
    it is the review queue instead: categories vendors' section names created
    that nobody has decided about, most restaurants first, so the one holding
    up the most vendors is the one at the top.

    `q` searches name and aliases, `kind` is the Restaurant / Store tab, and
    `sort=name` is the A to Z dropdown.
    """
    if sort not in {"default", "name", "-name"}:
        raise ValidationError("sort must be default, name or -name")
    counts = restaurant_counts()
    sections = (
        select(MenuCategory.category_id.label("category_id"), func.count().label("n"))
        .where(MenuCategory.category_id.is_not(None))
        .group_by(MenuCategory.category_id)
        .subquery()
    )
    products = product_counts()
    restaurant_count = func.coalesce(counts.c.restaurant_count, 0)
    stmt = (
        select(
            Category,
            restaurant_count,
            func.coalesce(sections.c.n, 0),
            func.coalesce(products.c.n, 0),
        )
        .outerjoin(counts, counts.c.category_id == Category.id)
        .outerjoin(sections, sections.c.category_id == Category.id)
        .outerjoin(products, products.c.category_id == Category.id)
    )
    conditions: list[ColumnElement[bool]] = []
    if pending_only:
        conditions.append(Category.reviewed_at.is_(None))
    if kind:
        wanted = kind.strip().upper()
        if wanted not in {"RESTAURANT", "STORE"}:
            raise ValidationError("kind must be RESTAURANT or STORE")
        conditions.append(Category.kind == wanted)
    if q and q.strip():
        from app.services.admin.common import like_pattern

        needle = q.strip()
        conditions.append(
            or_(
                Category.name.ilike(like_pattern(needle)),
                literal(match_key(needle)) == any_(Category.aliases),
            )
        )

    order: list[Any]
    if sort == "name":
        order = [Category.name.asc()]
    elif sort == "-name":
        order = [Category.name.desc()]
    else:
        order = [Category.sort_order.asc().nulls_last(), restaurant_count.desc(), Category.name]

    rows = await db.execute(stmt.where(*conditions).order_by(*order).limit(limit).offset(offset))
    total = await db.scalar(select(func.count()).select_from(Category).where(*conditions)) or 0
    return [to_admin_out(c, int(r), int(s), int(p)) for c, r, s, p in rows.all()], total


async def admin_create(db: AsyncSession, body: CategoryCreateRequest) -> CategoryAdminOut:
    """[EXTENDED] Add a category deliberately, ahead of any vendor."""
    name = " ".join(body.name.split())
    if not name:
        raise ValidationError("name cannot be blank")
    own_key = match_key(name)
    aliases = sorted({match_key(a) for a in body.aliases} - {own_key, ""})
    slug = slug_for(name)

    clash = await _claimed(db, {own_key, *aliases}, {slug})
    if clash is not None:
        raise ConflictError(f"'{clash.name}' already answers to that name")

    category = Category(
        name=name,
        slug=slug,
        image_url=body.image_url,
        sort_order=body.sort_order,
        aliases=aliases,
        is_active=body.is_active,
        commission_rate=body.commission_rate,
        kind=body.kind,
        # An administrator typing it IS the review, so it never enters the
        # queue and `is_active` is honoured as sent.
        reviewed_at=datetime.now(UTC),
    )
    db.add(category)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A category with that name already exists") from exc

    log.info("platform_category_created", category_id=str(category.id), slug=slug, by="admin")
    return to_admin_out(category, 0, 0)


async def admin_update(
    db: AsyncSession, category_id: uuid.UUID, body: CategoryUpdateRequest
) -> CategoryAdminOut:
    """[EXTENDED] Approve, rename, illustrate, pin, hide, or teach it new
    spellings.

    **Any call here marks the category reviewed**, including one that changes
    nothing. That is deliberate: it is how an operator says "I looked at this
    and it stays hidden" and stops it coming back in the queue forever.
    Approving is `is_active: true` on a pending row and nothing else.

    A rename keeps the slug (public id) and records the old name as an alias,
    so a vendor section named the old way still lands here.
    """
    category = await _get(db, category_id)
    fields = body.model_dump(exclude_unset=True)

    if fields.get("name") is not None:
        new_name = " ".join(fields["name"].split())
        if not new_name:
            raise ValidationError("name cannot be blank")
        if new_name != category.name:
            clash = await _claimed(db, {match_key(new_name)}, set(), exclude=category.id)
            if clash is not None:
                raise ConflictError(f"'{clash.name}' already answers to that name")
            old_key = match_key(category.name)
            category.name = new_name
            if old_key != match_key(new_name):
                category.aliases = sorted(set(category.aliases or []) | {old_key})

    if "image_url" in fields:
        category.image_url = fields["image_url"]
    if "sort_order" in fields:
        category.sort_order = fields["sort_order"]
    if fields.get("is_active") is not None:
        category.is_active = fields["is_active"]
    if "commission_rate" in fields:
        category.commission_rate = fields["commission_rate"]
    if fields.get("kind") is not None:
        category.kind = fields["kind"]

    if fields.get("aliases") is not None:
        aliases = sorted({match_key(a) for a in fields["aliases"]} - {match_key(category.name), ""})
        clash = await _claimed(db, set(aliases), set(), exclude=category.id)
        if clash is not None:
            raise ConflictError(f"'{clash.name}' already answers to one of those aliases")
        category.aliases = aliases

    was_pending = category.reviewed_at is None
    category.reviewed_at = datetime.now(UTC)
    await db.flush()
    log.info(
        "platform_category_updated",
        category_id=str(category.id),
        fields=sorted(fields),
        approved=was_pending and category.is_active,
    )
    return to_admin_out(category, *await _counts_for(db, category.id))


async def admin_delete(db: AsyncSession, category_id: uuid.UUID) -> None:
    """[EXTENDED] Remove a category nothing links to.

    Refused while menu sections still point at it. The FK would happily SET
    NULL, but that silently drops every one of those restaurants out of the
    chip they were under — merge is the operation that means "these belong
    somewhere else", and hiding is the one that means "not on the home screen".
    """
    category = await _get(db, category_id)
    linked = await db.scalar(
        select(func.count())
        .select_from(MenuCategory)
        .where(MenuCategory.category_id == category.id)
    )
    if linked:
        raise ConflictError(
            f"{linked} menu section(s) still list under this category. Merge it into "
            "another category, or set is_active=false to hide it instead."
        )
    await db.delete(category)
    await db.flush()
    log.info("platform_category_deleted", category_id=str(category_id), slug=category.slug)


async def admin_merge(
    db: AsyncSession, category_id: uuid.UUID, body: CategoryMergeRequest
) -> CategoryAdminOut:
    """[EXTENDED] Fold one category into another.

    Three things happen in one transaction: every section moves to the
    survivor, the survivor learns the loser's name and slug as aliases (so the
    same spelling resolves there from now on, and links to the old slug keep
    working through `find_by_name`), and the loser is deleted.
    """
    into_id = _as_uuid(body.into_id, "into_id")
    if into_id == category_id:
        raise ValidationError("A category cannot be merged into itself")
    source = await _get(db, category_id)
    target = await db.get(Category, into_id)
    if target is None:
        raise NotFoundError("Target category not found")

    moved = await db.execute(
        update(MenuCategory)
        .where(MenuCategory.category_id == source.id)
        .values(category_id=target.id)
    )
    learned = {match_key(source.name), source.slug, *(source.aliases or [])}
    target.aliases = sorted(
        (set(target.aliases or []) | learned) - {match_key(target.name), target.slug, ""}
    )
    await db.delete(source)
    await db.flush()

    log.info(
        "platform_category_merged",
        source_id=str(source.id),
        target_id=str(target.id),
        sections_moved=getattr(moved, "rowcount", None),
    )
    return to_admin_out(target, *await _counts_for(db, target.id))


__all__ = [
    "VISIBLE_RESTAURANT",
    "admin_create",
    "admin_delete",
    "admin_get",
    "admin_list",
    "admin_merge",
    "admin_update",
    "by_slug",
    "display_name",
    "find_by_name",
    "get_active",
    "get_by_id",
    "match_key",
    "resolve",
    "restaurant_counts",
    "sells_under",
    "slug_for",
    "to_ref",
]
