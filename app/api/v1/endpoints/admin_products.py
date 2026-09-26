"""Admin console — Product list, the product drawer, and Add Product [EXTENDED].

The vendor profile's Products tab is `GET /admin/products?restaurant_id=`, and
the Edit category drawer's product list is `GET /admin/products?category_id=`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import AdminProductCreateRequest, AdminProductUpdateRequest
from app.services import admin_product_service

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/products", summary="Every product on the platform [EXTENDED]")
async def list_products(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    q: Annotated[str | None, Query(description="Product or store name")] = None,
    restaurant_id: Annotated[str | None, Query(description="One vendor's products")] = None,
    category_id: Annotated[str | None, Query(description="One browse category")] = None,
    business_type: Annotated[
        str | None, Query(description="RESTAURANT, GROCERY or PHARMACY")
    ] = None,
    status: Annotated[
        str | None, Query(description="ACTIVE, HIDDEN (by an admin) or UNAVAILABLE (sold out)")
    ] = None,
    featured: Annotated[bool | None, Query(description="Only featured, or only not")] = None,
):
    """**[EXTENDED]** — featured first, then A to Z. Each row carries the
    commission the product is charged at and where that rate comes from."""
    rows, total = await admin_product_service.list_products(
        db,
        limit=page.limit,
        offset=page.offset,
        q=q,
        restaurant_id=restaurant_id,
        category_id=category_id,
        business_type=business_type,
        status=status,
        featured=featured,
    )
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/products/{product_id}", summary="The product drawer [EXTENDED]")
async def get_product(product_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — basics, variants, add-ons, and the pricing card: price,
    commission rate (and every level it could come from), commission and net."""
    return ok((await admin_product_service.get_product(db, product_id)).model_dump())


@router.patch("/products/{product_id}", summary="Edit, hide, feature or recategorise [EXTENDED]")
async def update_product(
    product_id: uuid.UUID, body: AdminProductUpdateRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — anything the vendor can edit, plus `commission_rate`,
    `is_hidden`, `is_featured` and `platform_category_id`. PATCH: omitted
    fields are left alone; `commission_rate: null` clears the product's own
    rate so the category's (then the restaurant's) applies again."""
    detail = await admin_product_service.update_product(db, admin, product_id, body)
    await db.commit()
    return ok(detail.model_dump())


@router.delete("/products/{product_id}", summary="Delete a product [EXTENDED]")
async def delete_product(product_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — soft delete, like the vendor's: gone from every menu,
    kept in order history. To take a product down without deleting the
    vendor's work, hide it instead."""
    await admin_product_service.delete_product(db, admin, product_id)
    await db.commit()
    return ok({"message": "Product deleted", "product_id": str(product_id)})


@router.post(
    "/vendors/{restaurant_id}/products",
    status_code=status.HTTP_201_CREATED,
    summary="Add a product to a vendor's menu [EXTENDED]",
)
async def create_product(
    restaurant_id: uuid.UUID, body: AdminProductCreateRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — the vendor profile's Add Product. Same body as the
    vendor's own `POST /vendor/menu/items`, except the product can be placed by
    browse category (`platform_category_id`) instead of by menu section, and
    may carry a `commission_rate` and `is_featured`."""
    detail = await admin_product_service.create_product(db, admin, restaurant_id, body)
    await db.commit()
    return ok(detail.model_dump())
