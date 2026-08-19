"""Menu catalog: categories, items, variants and add-ons.

**Ownership is proved by the schema, not by this module.** `menu_items` carries
a denormalized `restaurant_id` and a composite foreign key to
`(menu_categories.id, menu_categories.restaurant_id)`, so an item can only exist
under a category belonging to the same restaurant. A forged `category_id` cannot
smuggle a row onto someone else's menu even if every check below were removed.

What this module adds on top is a *good error*: the constraint would raise an
opaque `IntegrityError`, and a vendor deserves "that category isn't yours"
instead of a 500.

Every function takes the `Restaurant` resolved by
``app.api.deps.get_vendor_restaurant`` rather than a restaurant id from the
request. There is no code path here that trusts a caller-supplied restaurant.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.money import to_major, to_minor
from app.models.menu import ItemAddOn, ItemVariant, MenuCategory, MenuItem
from app.models.restaurant import Restaurant
from app.schemas.requests import (
    AddOnRequest,
    MenuCategoryCreateRequest,
    MenuCategoryUpdateRequest,
    MenuItemCreateRequest,
    MenuItemUpdateRequest,
    MenuReorderRequest,
    VariantRequest,
)
from app.schemas.vendor import (
    AddOnOut,
    MenuCategoryOut,
    MenuCategoryWithItems,
    MenuItemOut,
    VariantOut,
    VendorMenu,
)

log = structlog.get_logger()


def _as_uuid(value: str, what: str) -> uuid.UUID:
    """Parse a client-supplied id.

    FastAPI validates path parameters, but ids inside a request body arrive as
    plain strings. Without this, a malformed id reaches the driver and comes
    back as a 500 rather than the 400 it is.
    """
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{what} is not a valid id") from exc


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def variant_to_out(variant: ItemVariant) -> VariantOut:
    return VariantOut(
        id=str(variant.id),
        name=variant.name,
        price=to_major(variant.price),
        is_default=variant.is_default,
        is_available=variant.is_available,
        sort_order=variant.sort_order,
    )


def add_on_to_out(add_on: ItemAddOn) -> AddOnOut:
    return AddOnOut(
        id=str(add_on.id),
        name=add_on.name,
        price=to_major(add_on.price),
        is_available=add_on.is_available,
        sort_order=add_on.sort_order,
    )


def item_to_out(item: MenuItem) -> MenuItemOut:
    """Requires `variants` and `add_ons` to be eagerly loaded.

    Both relationships are `lazy="raise"`, so a caller that forgets the
    `selectinload` gets an immediate, obvious error instead of an N+1 that only
    shows up as latency in production.
    """
    return MenuItemOut(
        id=str(item.id),
        restaurant_id=str(item.restaurant_id),
        category_id=str(item.category_id),
        name=item.name,
        description=item.description,
        base_price=to_major(item.base_price),
        image_url=item.image_url,
        is_available=item.is_available,
        is_veg=item.is_veg,
        prep_time_mins=item.prep_time_mins,
        sort_order=item.sort_order,
        variants=[
            variant_to_out(v)
            for v in sorted(item.variants, key=lambda v: (v.sort_order, v.name))
        ],
        add_ons=[
            add_on_to_out(a)
            for a in sorted(item.add_ons, key=lambda a: (a.sort_order, a.name))
        ],
    )


def category_to_out(category: MenuCategory, item_count: int = 0) -> MenuCategoryOut:
    return MenuCategoryOut(
        id=str(category.id),
        restaurant_id=str(category.restaurant_id),
        name=category.name,
        sort_order=category.sort_order,
        is_active=category.is_active,
        item_count=item_count,
    )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


async def _get_category(db: AsyncSession, restaurant: Restaurant, category_id) -> MenuCategory:
    """Fetch a category, scoped to this restaurant.

    The restaurant predicate is what turns someone else's category id into a
    404. Fetching by primary key alone and checking ownership afterwards would
    work too, but this way an ownership check can never be forgotten.
    """
    result = await db.execute(
        select(MenuCategory).where(
            MenuCategory.id == category_id, MenuCategory.restaurant_id == restaurant.id
        )
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise NotFoundError("Menu category not found")
    return category


async def _item_counts(db: AsyncSession, restaurant: Restaurant) -> dict[uuid.UUID, int]:
    """Live item counts per category, in one query rather than one per row."""
    result = await db.execute(
        select(MenuItem.category_id, func.count())
        .where(MenuItem.restaurant_id == restaurant.id, MenuItem.deleted_at.is_(None))
        .group_by(MenuItem.category_id)
    )
    return {row[0]: row[1] for row in result.all()}


async def list_categories(
    db: AsyncSession, restaurant: Restaurant, include_inactive: bool = True
) -> list[MenuCategoryOut]:
    """Spec #44.

    `include_inactive` defaults to true because this is the vendor's own view:
    a deactivated category that vanished from the owner's screen could never be
    reactivated.
    """
    stmt = select(MenuCategory).where(MenuCategory.restaurant_id == restaurant.id)
    if not include_inactive:
        stmt = stmt.where(MenuCategory.is_active.is_(True))
    result = await db.execute(stmt.order_by(MenuCategory.sort_order, MenuCategory.name))
    counts = await _item_counts(db, restaurant)
    return [category_to_out(c, counts.get(c.id, 0)) for c in result.scalars().all()]


async def create_category(
    db: AsyncSession, restaurant: Restaurant, body: MenuCategoryCreateRequest
) -> MenuCategoryOut:
    """[EXTENDED] The endpoint that unblocks menu building."""
    category = MenuCategory(
        restaurant_id=restaurant.id,
        name=body.name.strip(),
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(category)
    try:
        await db.flush()
    except IntegrityError as exc:
        # uq_menu_categories_name — (restaurant_id, name).
        await db.rollback()
        raise ConflictError(f"A category named '{body.name.strip()}' already exists") from exc

    log.info(
        "menu_category_created",
        restaurant_id=str(restaurant.id),
        category_id=str(category.id),
    )
    return category_to_out(category, 0)


async def update_category(
    db: AsyncSession, restaurant: Restaurant, category_id, body: MenuCategoryUpdateRequest
) -> MenuCategoryOut:
    category = await _get_category(db, restaurant, category_id)
    fields = body.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"] is not None:
        category.name = fields["name"].strip()
    if "sort_order" in fields and fields["sort_order"] is not None:
        category.sort_order = fields["sort_order"]
    if "is_active" in fields and fields["is_active"] is not None:
        category.is_active = fields["is_active"]

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Another category already uses that name") from exc

    counts = await _item_counts(db, restaurant)
    return category_to_out(category, counts.get(category.id, 0))


async def delete_category(db: AsyncSession, restaurant: Restaurant, category_id) -> None:
    """Hard delete, and only for an empty category.

    `fk_menu_items_category` is ON DELETE CASCADE, so deleting a populated
    category would silently destroy every item under it — and menu items are
    soft-deleted precisely because order history references them. Refusing is
    the only safe answer; the vendor can deactivate the category instead, which
    hides it from customers and keeps the items intact.

    "Empty" means no *live* items. A category holding only soft-deleted ones is
    still deletable, and that does drop those rows — `order_items.menu_item_id`
    becomes NULL. The cost is bounded and deliberate: `order_items` snapshots
    `item_name`, and `analytics` groups on `(menu_item_id, item_name)` precisely
    so an orphaned line still reports under the name it sold as. The alternative
    — a category that can never be deleted once anything was ever added to it —
    is worse for a menu that changes every season.
    """
    category = await _get_category(db, restaurant, category_id)

    live = await db.scalar(
        select(func.count())
        .select_from(MenuItem)
        .where(MenuItem.category_id == category.id, MenuItem.deleted_at.is_(None))
    )
    if live:
        raise ConflictError(
            f"This category still holds {live} item(s). Move or delete them first, "
            "or set is_active=false to hide the category without losing them."
        )

    await db.delete(category)
    await db.flush()
    log.info(
        "menu_category_deleted",
        restaurant_id=str(restaurant.id),
        category_id=str(category_id),
    )


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


async def _get_item(db: AsyncSession, restaurant: Restaurant, item_id) -> MenuItem:
    """Fetch a live item with its options, scoped to this restaurant."""
    result = await db.execute(
        select(MenuItem)
        .where(
            MenuItem.id == item_id,
            MenuItem.restaurant_id == restaurant.id,
            MenuItem.deleted_at.is_(None),
        )
        .options(selectinload(MenuItem.variants), selectinload(MenuItem.add_ons))
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFoundError("Menu item not found")
    return item


def _apply_positional_order(entries: list) -> None:
    """Fall back to payload position when the client sets no explicit order.

    `sort_order` defaults to 0, so a client that just lists its variants in the
    order it wants would otherwise get all-zeros and be sorted alphabetically —
    turning "Half, Full" into "Full, Half" and quietly rearranging every menu
    built without explicit indices. Only applied when every entry is still at
    the default, so a client that does set the field keeps full control.
    """
    if entries and all(e.sort_order == 0 for e in entries):
        for position, entry in enumerate(entries):
            entry.sort_order = position


def _resolve_default(variants: list[VariantRequest]) -> None:
    """Enforce `uq_item_variants_one_default` before the database has to.

    The partial unique index allows at most one default per item. Two flagged
    defaults would be an IntegrityError; none at all is legal but leaves the
    client with nothing to preselect, so the first variant is promoted.
    """
    flagged = [v for v in variants if v.is_default]
    if len(flagged) > 1:
        raise ValidationError("Only one variant can be the default")
    if variants and not flagged:
        variants[0].is_default = True


async def _sync_variants(db: AsyncSession, item: MenuItem, payload: list[VariantRequest]) -> None:
    """Apply a replace-set of variants, preserving ids where the client sent them.

    Preserving ids matters more than it looks: `cart_items.variant_id` has a
    composite FK with ON DELETE CASCADE, so dropping and recreating a variant on
    every price edit would empty every cart holding that item. Matching on id
    means a price change is a price change.
    """
    _apply_positional_order(payload)
    _resolve_default(payload)
    existing = {v.id: v for v in item.variants}
    keep: set[uuid.UUID] = set()

    for entry in payload:
        if entry.id:
            variant_id = _as_uuid(entry.id, "variant id")
            variant = existing.get(variant_id)
            if variant is None:
                raise NotFoundError(f"Variant {entry.id} does not belong to this item")
            variant.name = entry.name.strip()
            variant.price = to_minor(entry.price)
            variant.is_available = entry.is_available
            variant.sort_order = entry.sort_order
            # Cleared for everyone first (below) so the unique index never sees
            # two defaults mid-transaction.
            keep.add(variant.id)
        else:
            variant = ItemVariant(
                menu_item_id=item.id,
                name=entry.name.strip(),
                price=to_minor(entry.price),
                is_available=entry.is_available,
                sort_order=entry.sort_order,
                is_default=False,
            )
            db.add(variant)
            item.variants.append(variant)

    for variant in list(item.variants):
        if variant.id is not None and variant.id not in keep and variant.id in existing:
            item.variants.remove(variant)
            await db.delete(variant)

    # Two passes over is_default: clear every flag, flush, then set the one
    # winner. A single pass can transiently hold two defaults and trip
    # uq_item_variants_one_default even though the end state is legal.
    for variant in item.variants:
        variant.is_default = False
    await db.flush()

    default_name = next((v.name.strip() for v in payload if v.is_default), None)
    if default_name is not None:
        for variant in item.variants:
            if variant.name == default_name:
                variant.is_default = True
                break
    await db.flush()


async def _sync_add_ons(db: AsyncSession, item: MenuItem, payload: list[AddOnRequest]) -> None:
    """Replace-set for add-ons. Same id-preservation contract as variants."""
    _apply_positional_order(payload)
    existing = {a.id: a for a in item.add_ons}
    keep: set[uuid.UUID] = set()

    for entry in payload:
        if entry.id:
            add_on_id = _as_uuid(entry.id, "add-on id")
            add_on = existing.get(add_on_id)
            if add_on is None:
                raise NotFoundError(f"Add-on {entry.id} does not belong to this item")
            add_on.name = entry.name.strip()
            add_on.price = to_minor(entry.price)
            add_on.is_available = entry.is_available
            add_on.sort_order = entry.sort_order
            keep.add(add_on.id)
        else:
            add_on = ItemAddOn(
                menu_item_id=item.id,
                name=entry.name.strip(),
                price=to_minor(entry.price),
                is_available=entry.is_available,
                sort_order=entry.sort_order,
            )
            db.add(add_on)
            item.add_ons.append(add_on)

    for add_on in list(item.add_ons):
        if add_on.id is not None and add_on.id not in keep and add_on.id in existing:
            item.add_ons.remove(add_on)
            await db.delete(add_on)

    await db.flush()


async def create_item(
    db: AsyncSession, restaurant: Restaurant, body: MenuItemCreateRequest
) -> MenuItemOut:
    """Spec #45. Item, variants and add-ons in one transaction.

    All or nothing on purpose: an item that saved but whose variants did not is
    an item priced from a `base_price` that decision D4 says is display-only —
    it would sell at the wrong price.
    """
    category_id = _as_uuid(body.category_id, "category_id")
    category = await _get_category(db, restaurant, category_id)

    item = MenuItem(
        category_id=category.id,
        restaurant_id=restaurant.id,
        name=body.name.strip(),
        description=body.description,
        base_price=to_minor(body.base_price),
        image_url=body.image_url,
        is_available=body.is_available,
        is_veg=body.is_veg,
        prep_time_mins=body.prep_time_mins,
        sort_order=body.sort_order,
    )
    db.add(item)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Menu item could not be created") from exc

    # Rows are inserted directly rather than through the collections. `variants`
    # and `add_ons` are `lazy="raise"`, and assigning to an unloaded collection
    # on a persistent object makes SQLAlchemy load it first to compute the diff
    # — which raises. Creation has nothing to diff against anyway.
    variants = list(body.variants)
    _apply_positional_order(variants)
    _resolve_default(variants)
    add_ons = list(body.add_ons)
    _apply_positional_order(add_ons)
    try:
        for entry in variants:
            db.add(
                ItemVariant(
                    menu_item_id=item.id,
                    name=entry.name.strip(),
                    price=to_minor(entry.price),
                    is_available=entry.is_available,
                    sort_order=entry.sort_order,
                    is_default=entry.is_default,
                )
            )
        for add_on in add_ons:
            db.add(
                ItemAddOn(
                    menu_item_id=item.id,
                    name=add_on.name.strip(),
                    price=to_minor(add_on.price),
                    is_available=add_on.is_available,
                    sort_order=add_on.sort_order,
                )
            )
        await db.flush()
    except IntegrityError as exc:
        # uq_item_variants_name / uq_item_add_ons_name — two options with the
        # same name on one item.
        await db.rollback()
        raise ConflictError("Variant and add-on names must be unique within an item") from exc

    log.info(
        "menu_item_created",
        restaurant_id=str(restaurant.id),
        item_id=str(item.id),
        variants=len(variants),
        add_ons=len(add_ons),
    )
    # Re-read so the response carries what was actually persisted, with both
    # collections eagerly loaded.
    return item_to_out(await _get_item(db, restaurant, item.id))


async def get_item(db: AsyncSession, restaurant: Restaurant, item_id) -> MenuItemOut:
    return item_to_out(await _get_item(db, restaurant, item_id))


async def update_item(
    db: AsyncSession, restaurant: Restaurant, item_id, body: MenuItemUpdateRequest
) -> MenuItemOut:
    """[EXTENDED] Edit an item in place.

    Only fields actually present in the request body are touched, so a client
    that PATCHes `{"base_price": 320}` cannot accidentally clear a description
    it never sent.
    """
    item = await _get_item(db, restaurant, item_id)
    fields = body.model_dump(exclude_unset=True)

    if "category_id" in fields and fields["category_id"] is not None:
        category = await _get_category(
            db, restaurant, _as_uuid(fields["category_id"], "category_id")
        )
        item.category_id = category.id
    if "name" in fields and fields["name"] is not None:
        item.name = fields["name"].strip()
    if "description" in fields:
        item.description = fields["description"]
    if "base_price" in fields and fields["base_price"] is not None:
        item.base_price = to_minor(fields["base_price"])
    if "image_url" in fields:
        item.image_url = fields["image_url"]
    if "is_available" in fields and fields["is_available"] is not None:
        item.is_available = fields["is_available"]
    if "is_veg" in fields and fields["is_veg"] is not None:
        item.is_veg = fields["is_veg"]
    if "prep_time_mins" in fields:
        item.prep_time_mins = fields["prep_time_mins"]
    if "sort_order" in fields and fields["sort_order"] is not None:
        item.sort_order = fields["sort_order"]

    try:
        if body.variants is not None:
            await _sync_variants(db, item, list(body.variants))
        if body.add_ons is not None:
            await _sync_add_ons(db, item, list(body.add_ons))
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Variant and add-on names must be unique within an item") from exc

    log.info("menu_item_updated", restaurant_id=str(restaurant.id), item_id=str(item.id))
    return item_to_out(item)


async def set_item_status(
    db: AsyncSession, restaurant: Restaurant, item_id, is_available: bool
) -> MenuItemOut:
    """Spec #46. The high-frequency 'sold out' toggle.

    Kept as its own endpoint rather than folded into PATCH: it is pressed
    dozens of times a service, from a list screen that holds no other state, and
    a one-field body is the difference between a tap that works on a bad
    connection and one that does not.
    """
    item = await _get_item(db, restaurant, item_id)
    item.is_available = is_available
    await db.flush()
    return item_to_out(item)


async def delete_item(db: AsyncSession, restaurant: Restaurant, item_id) -> None:
    """Soft delete — `deleted_at`, never a DELETE.

    `order_items.menu_item_id` is ON DELETE SET NULL, so a hard delete would
    survive, but analytics keyed on `menu_item_id` would quietly lose the row
    and every historical "top item" figure would shift. The column existed from
    the start; this is the first thing to write it.
    """
    item = await _get_item(db, restaurant, item_id)
    item.deleted_at = datetime.now(UTC)
    item.is_available = False
    await db.flush()
    log.info("menu_item_deleted", restaurant_id=str(restaurant.id), item_id=str(item_id))


# ---------------------------------------------------------------------------
# Whole menu & ordering
# ---------------------------------------------------------------------------


async def get_menu(db: AsyncSession, restaurant: Restaurant) -> VendorMenu:
    """[EXTENDED] The vendor's own menu tree, nothing filtered out.

    The public `GET /restaurants/{id}/menu` hides inactive categories and
    unavailable items. That is right for a customer and useless for the owner,
    who needs to see exactly what they have in order to change it.
    """
    cat_result = await db.execute(
        select(MenuCategory)
        .where(MenuCategory.restaurant_id == restaurant.id)
        .order_by(MenuCategory.sort_order, MenuCategory.name)
    )
    categories = list(cat_result.scalars().all())

    item_result = await db.execute(
        select(MenuItem)
        .where(MenuItem.restaurant_id == restaurant.id, MenuItem.deleted_at.is_(None))
        .options(selectinload(MenuItem.variants), selectinload(MenuItem.add_ons))
        .order_by(MenuItem.sort_order, MenuItem.name)
    )
    items = list(item_result.scalars().all())

    by_category: dict[uuid.UUID, list[MenuItem]] = {}
    for item in items:
        by_category.setdefault(item.category_id, []).append(item)

    return VendorMenu(
        restaurant_id=str(restaurant.id),
        categories=[
            MenuCategoryWithItems(
                **category_to_out(c, len(by_category.get(c.id, []))).model_dump(),
                items=[item_to_out(i) for i in by_category.get(c.id, [])],
            )
            for c in categories
        ],
    )


async def reorder(db: AsyncSession, restaurant: Restaurant, body: MenuReorderRequest) -> dict:
    """[EXTENDED] Apply a drag-and-drop reorder to categories and items at once.

    Every id is verified against this restaurant before anything is written, so
    a payload containing one foreign id changes nothing at all rather than
    applying half of itself.
    """
    if not body.categories and not body.items:
        raise ValidationError("Nothing to reorder")

    category_ids = [_as_uuid(e.id, "category id") for e in body.categories]
    item_ids = [_as_uuid(e.id, "item id") for e in body.items]

    if category_ids:
        found = await db.execute(
            select(MenuCategory.id).where(
                MenuCategory.id.in_(category_ids), MenuCategory.restaurant_id == restaurant.id
            )
        )
        owned = {row[0] for row in found.all()}
        missing = [str(i) for i in category_ids if i not in owned]
        if missing:
            raise NotFoundError(f"Categories not found on this menu: {', '.join(missing)}")

    if item_ids:
        found = await db.execute(
            select(MenuItem.id).where(
                MenuItem.id.in_(item_ids),
                MenuItem.restaurant_id == restaurant.id,
                MenuItem.deleted_at.is_(None),
            )
        )
        owned = {row[0] for row in found.all()}
        missing = [str(i) for i in item_ids if i not in owned]
        if missing:
            raise NotFoundError(f"Items not found on this menu: {', '.join(missing)}")

    for entry, cid in zip(body.categories, category_ids, strict=True):
        category = await db.get(MenuCategory, cid)
        if category is not None:
            category.sort_order = entry.sort_order
    for entry, iid in zip(body.items, item_ids, strict=True):
        item = await db.get(MenuItem, iid)
        if item is not None:
            item.sort_order = entry.sort_order

    await db.flush()
    return {"categories_updated": len(category_ids), "items_updated": len(item_ids)}
