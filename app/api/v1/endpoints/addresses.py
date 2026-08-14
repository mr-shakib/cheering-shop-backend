"""Addresses — spec endpoints #14–18. Customer only."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CustomerUser, DbSession, Paginated
from app.core.errors import NotImplementedYetError
from app.schemas.requests import AddressCreateRequest

router = APIRouter(prefix="/users/me/addresses", tags=["Addresses"])


@router.get("", summary="List saved addresses")
async def list_addresses(user: CustomerUser, db: DbSession, page: Paginated):
    """Spec #14."""
    raise NotImplementedYetError()


@router.post("", status_code=status.HTTP_201_CREATED, summary="Save an address")
async def create_address(body: AddressCreateRequest, user: CustomerUser, db: DbSession):
    """Spec #15.

    If `is_default` is true, other defaults are unset in the same transaction.
    A partial unique index makes a concurrent double-set fail rather than
    silently leaving the user with two default addresses.
    """
    raise NotImplementedYetError()


@router.put("/{address_id}", summary="Replace an address")
async def update_address(
    address_id: uuid.UUID, body: AddressCreateRequest, user: CustomerUser, db: DbSession
):
    """Spec #16."""
    raise NotImplementedYetError()


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an address")
async def delete_address(address_id: uuid.UUID, user: CustomerUser, db: DbSession):
    """Spec #17. Safe to hard-delete: orders snapshot the address at purchase."""
    raise NotImplementedYetError()


@router.patch("/{address_id}/default", summary="Set default address")
async def set_default_address(address_id: uuid.UUID, user: CustomerUser, db: DbSession):
    """Spec #18."""
    raise NotImplementedYetError()
