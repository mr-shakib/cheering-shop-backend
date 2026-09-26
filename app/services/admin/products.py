"""Products across every vendor: the list, the drawer, and admin edits.

Edits reuse the vendor's own menu service for everything a vendor can change
(name, price, image, variants …), so a product edited from the console obeys
exactly the rules it does in the vendor app. Only the admin-only fields are
handled here: commission, hiding, featuring, and moving a product under a
different browse category.

Browse categories hang off menu *sections*, not products. Moving a product to
a category therefore moves it into its restaurant's section for that category,
creating the section (named after the category) when the restaurant has none.
"""

import uuid

import structlog
from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import NotFoundError, ValidationError
from app.core.money import percentage_of, to_major
from app.models.category import Category
from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.admin import AdminProductDetail, AdminProductRow, ProductCommission
from app.schemas.requests import (
    AdminProductCreateRequest,
    AdminProductUpdateRequest,
    MenuCategoryCreateRequest,
    MenuItemCreateRequest,
    MenuItemUpdateRequest,
)
from app.services import category_service, commission, menu_service
from app.services.admin.common import (
    business_type_of,
    like_pattern,
    parse_uuid,
    validate_business_type,
)

log = structlog.get_logger()

STATUSES = ("ACTIVE", "HIDDEN", "UNAVAILABLE")
_ADMIN_ONLY = {"commission_rate", "is_hidden", "is_featured", "platform_category_id"}


def _status(item: MenuItem) -> str:
    if item.is_hidden:
        return "HIDDEN"
    return "ACTIVE" if item.is_available else "UNAVAILABLE"


def _rows_query() -> Select:
    return (
        select(MenuItem, MenuCategory, Category, Restaurant, business_type_of(Restaurant.id))
        .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
        .outerjoin(Category, Category.id == MenuCategory.category_id)
        .join(Restaurant, Restaurant.id == MenuItem.restaurant_id)
        .where(MenuItem.deleted_at.is_(None))
    )


def _commission(item: MenuItem, category: Category | None, r: Restaurant) -> ProductCommission:
    category_rate = category.commission_rate if category else None
    rate, source = commission.resolve(item.commission_rate, category_rate, r.commission_rate)
    return ProductCommission(
        rate=rate,
        source=source,
        product_rate=float(item.commission_rate) if item.commission_rate is not None else None,
        category_rate=float(category_rate) if category_rate is not None else None,
        restaurant_rate=float(r.commission_rate),
    )


def _to_row(
    item: MenuItem,
    section: MenuCategory,
    category: Category | None,
    restaurant: Restaurant,
    business_type: str | None,
) -> AdminProductRow:
    return AdminProductRow(
        id=str(item.id),
        name=item.name,
        image_url=item.image_url,
        restaurant_id=str(restaurant.id),
        restaurant_name=restaurant.name,
        business_type=business_type,
        section_id=str(section.id),
        section_name=section.name,
        platform_category=category_service.to_ref(category) if category else None,
        base_price=to_major(item.base_price),
        status=_status(item),
        is_available=item.is_available,
        is_hidden=item.is_hidden,
        is_featured=item.is_featured,
        commission=_commission(item, category, restaurant),
        created_at=item.created_at,
    )


async def list_products(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    q: str | None = None,
    restaurant_id: str | None = None,
    category_id: str | None = None,
    business_type: str | None = None,
    status: str | None = None,
    featured: bool | None = None,
) -> tuple[list[AdminProductRow], int]:
    """Featured first, then by name. `category_id` is a browse category —
    the Edit category drawer's product list is this with that filter."""
    conditions: list[ColumnElement[bool]] = []
    if q and q.strip():
        pattern = like_pattern(q.strip())
        conditions.append(or_(MenuItem.name.ilike(pattern), Restaurant.name.ilike(pattern)))
    if (rid := parse_uuid(restaurant_id, "restaurant_id")) is not None:
        conditions.append(MenuItem.restaurant_id == rid)
    if (cid := parse_uuid(category_id, "category_id")) is not None:
        conditions.append(MenuCategory.category_id == cid)
    if (kind := validate_business_type(business_type)) is not None:
        conditions.append(business_type_of(Restaurant.id) == kind)
    if status:
        wanted = status.strip().upper()
        if wanted not in STATUSES:
            raise ValidationError(f"status must be one of: {', '.join(STATUSES)}")
        conditions.append(
            {
                "HIDDEN": MenuItem.is_hidden.is_(True),
                "UNAVAILABLE": (MenuItem.is_hidden.is_(False) & MenuItem.is_available.is_(False)),
                "ACTIVE": (MenuItem.is_hidden.is_(False) & MenuItem.is_available.is_(True)),
            }[wanted]
        )
    if featured is not None:
        conditions.append(MenuItem.is_featured.is_(featured))

    base = _rows_query().where(*conditions)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(case((MenuItem.is_featured, 0), else_=1), MenuItem.name, MenuItem.id)
        .limit(limit)
        .offset(offset)
    )
    return [_to_row(*row) for row in result.all()], total


async def _load(db: AsyncSession, product_id: uuid.UUID) -> tuple:
    row = (
        await db.execute(
            _rows_query()
            .where(MenuItem.id == product_id)
            .options(selectinload(MenuItem.variants), selectinload(MenuItem.add_ons))
            # Refresh rows already in the session: after an edit, the drawer
            # must show what was written, variants and add-ons included.
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise NotFoundError("Product not found")
    return tuple(row)


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> AdminProductDetail:
    item, section, category, restaurant, business_type = await _load(db, product_id)
    row = _to_row(item, section, category, restaurant, business_type)
    commission_minor = percentage_of(item.base_price, int(round(row.commission.rate * 10_000)))
    vendor_view = menu_service.item_to_out(item)
    return AdminProductDetail(
        **row.model_dump(),
        description=item.description,
        is_veg=item.is_veg,
        prep_time_mins=item.prep_time_mins,
        variants=vendor_view.variants,
        add_ons=vendor_view.add_ons,
        commission_amount=to_major(commission_minor),
        net_amount=to_major(item.base_price - commission_minor),
    )


async def _section_for(db: AsyncSession, restaurant: Restaurant, category_id: str) -> uuid.UUID:
    """The restaurant's menu section for a browse category, made if missing."""
    parsed = parse_uuid(category_id, "platform_category_id")
    category = await category_service.get_by_id(db, parsed) if parsed else None
    if category is None:
        raise NotFoundError("No browse category with that id")
    existing = await db.scalar(
        select(MenuCategory.id)
        .where(MenuCategory.restaurant_id == restaurant.id, MenuCategory.category_id == category.id)
        .order_by(MenuCategory.sort_order, MenuCategory.name)
        .limit(1)
    )
    if existing is not None:
        return existing
    created = await menu_service.create_category(
        db,
        restaurant,
        MenuCategoryCreateRequest(name=category.name, platform_category_id=str(category.id)),
    )
    return uuid.UUID(created.id)


async def update_product(
    db: AsyncSession, admin: User, product_id: uuid.UUID, body: AdminProductUpdateRequest
) -> AdminProductDetail:
    item, _, _, restaurant, _ = await _load(db, product_id)
    fields = body.model_dump(exclude_unset=True)

    vendor_fields = {k: v for k, v in fields.items() if k not in _ADMIN_ONLY}
    if body.platform_category_id is not None:
        vendor_fields["category_id"] = str(
            await _section_for(db, restaurant, body.platform_category_id)
        )
    if vendor_fields:
        # Re-validated as the vendor's own request, so every vendor-side rule
        # (variant defaults, unique option names …) applies unchanged.
        await menu_service.update_item(
            db, restaurant, item.id, MenuItemUpdateRequest.model_validate(vendor_fields)
        )

    if "commission_rate" in fields:
        item.commission_rate = fields["commission_rate"]
    if fields.get("is_hidden") is not None:
        item.is_hidden = fields["is_hidden"]
    if fields.get("is_featured") is not None:
        item.is_featured = fields["is_featured"]
    await db.flush()

    log.info(
        "admin_product_updated",
        product_id=str(item.id),
        admin_id=str(admin.id),
        fields=sorted(fields),
    )
    return await get_product(db, item.id)


async def delete_product(db: AsyncSession, admin: User, product_id: uuid.UUID) -> None:
    """Soft delete, exactly as the vendor's delete: order history keeps it."""
    item, _, _, restaurant, _ = await _load(db, product_id)
    await menu_service.delete_item(db, restaurant, item.id)
    log.info("admin_product_deleted", product_id=str(product_id), admin_id=str(admin.id))


async def create_product(
    db: AsyncSession, admin: User, restaurant_id: uuid.UUID, body: AdminProductCreateRequest
) -> AdminProductDetail:
    restaurant = await db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("No vendor with that id")
    fields = body.model_dump(exclude={"platform_category_id", "commission_rate", "is_featured"})
    if body.platform_category_id is not None:
        fields["category_id"] = str(await _section_for(db, restaurant, body.platform_category_id))
    created = await menu_service.create_item(
        db, restaurant, MenuItemCreateRequest.model_validate(fields)
    )

    item, *_ = await _load(db, uuid.UUID(created.id))
    item.commission_rate = body.commission_rate
    item.is_featured = body.is_featured
    await db.flush()
    log.info("admin_product_created", product_id=created.id, admin_id=str(admin.id))
    return await get_product(db, item.id)
