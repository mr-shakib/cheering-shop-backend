"""Saved delivery addresses — spec endpoints #24–25."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.core.responses import ok
from app.schemas.requests import AddressCreateRequest
from app.services import account_service

router = APIRouter(prefix="/users/me/addresses", tags=["Addresses"])


@router.get("", summary="List saved addresses")
async def list_addresses(user: CurrentUser, db: DbSession):
    """Spec #24. Default first — it is the one checkout preselects."""
    addresses = await account_service.list_addresses(db, user.id)
    return ok([a.model_dump() for a in addresses])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Save an address")
async def create_address(body: AddressCreateRequest, user: CurrentUser, db: DbSession):
    """Spec #25.

    The first address a customer saves becomes their default automatically;
    otherwise checkout opens with nothing selected on the very first order,
    which is the worst possible moment to make someone hunt through a picker.
    """
    address = await account_service.create_address(db, user.id, body)
    await db.commit()
    return ok(address.model_dump())


@router.put("/{address_id}", summary="Replace an address")
async def replace_address(
    address_id: uuid.UUID, body: AddressCreateRequest, user: CurrentUser, db: DbSession
):
    """**[EXTENDED]** — the Address screen's edit form. Full replacement."""
    address = await account_service.replace_address(db, user.id, str(address_id), body)
    await db.commit()
    return ok(address.model_dump())


@router.delete(
    "/{address_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an address"
)
async def delete_address(address_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """**[EXTENDED]**. Deleting the default promotes the next most recent one,
    so a customer is never left with addresses but no default.

    Past orders keep their address either way: `delivery_address_id` is
    ON DELETE SET NULL and the order carries a text snapshot alongside it.
    """
    await account_service.delete_address(db, user.id, str(address_id))
    await db.commit()


@router.patch("/{address_id}/default", summary="Set default address")
async def set_default_address(address_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """**[EXTENDED]**. Demotes the previous default in the same transaction —
    two defaults is a state the checkout screen cannot render."""
    address = await account_service.set_default(db, user.id, str(address_id))
    await db.commit()
    return ok(address.model_dump())
