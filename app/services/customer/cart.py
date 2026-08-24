"""Cart and checkout — spec #26–28.

**The cart stores configuration, never money.** Quantity, which item, which
variant, which add-ons — and nothing else. Prices are recomputed on every read
from the live menu, so a vendor's price change is visible to the customer
before they commit rather than being honoured at a stale figure because
something sat in a cart overnight.

The single-restaurant rule is enforced twice on purpose. The database refuses a
cross-restaurant line outright through paired composite foreign keys
(`fk_cart_items_cart` and `fk_cart_items_menu_item` share `restaurant_id`, so
one row cannot satisfy both for two different restaurants). The check in
`modify_item` exists only to turn that into a courteous 409 instead of letting
an integrity error surface as a 500.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.money import to_major
from app.models.cart import Cart, CartItem, CartItemAddOn
from app.models.enums import RestaurantStatus
from app.models.menu import ItemAddOn, ItemVariant, MenuItem
from app.models.restaurant import Restaurant
from app.schemas.customer import CartLineOut, CartOut
from app.schemas.requests import CartItemRequest
from app.services.pricing import QuoteLine


def _fingerprint(add_on_ids: list[uuid.UUID]) -> str:
    """Stable id for a set of add-ons.

    Sorted before hashing so {cheese, bacon} and {bacon, cheese} collapse into
    one cart line, while {cheese} stays separate. This is what makes tapping
    "+" twice on an identically configured item increment a row rather than
    create a duplicate — the UNIQUE constraint keys on it.
    """
    if not add_on_ids:
        return ""
    joined = ",".join(sorted(str(a) for a in add_on_ids))
    return hashlib.sha256(joined.encode()).hexdigest()[:32]


def _as_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValidationError(f"{what} is not a valid id") from exc


async def _load_cart(db: AsyncSession, user_id: uuid.UUID) -> Cart | None:
    """Load the cart and its lines.

    `populate_existing` matters: after `modify_item` has added a row, the Cart
    is already in the identity map with the collection it was loaded (or
    created) with, and SQLAlchemy will NOT overwrite an already-populated
    relationship by default. Without this, the response to "add to cart" would
    show the cart as it was before the add.
    """
    return await db.scalar(
        select(Cart)
        .where(Cart.user_id == user_id)
        .options(selectinload(Cart.items).selectinload(CartItem.add_ons))
        .execution_options(populate_existing=True)
    )


async def _price_lines(db: AsyncSession, cart: Cart) -> tuple[list[CartLineOut], list[QuoteLine]]:
    """Resolve every line against the LIVE menu.

    Returns both the wire shape and the pricing shape from one pass, because
    the two callers (GET /cart and the checkout quote) need the same lookups
    and doing them twice would double the query count for no benefit.
    """
    if not cart.items:
        return [], []

    item_ids = {i.menu_item_id for i in cart.items}
    variant_ids = {i.variant_id for i in cart.items if i.variant_id}
    add_on_ids = {a.add_on_id for i in cart.items for a in i.add_ons}

    items = {
        m.id: m
        for m in (
            await db.scalars(
                select(MenuItem).where(MenuItem.id.in_(item_ids), MenuItem.deleted_at.is_(None))
            )
        ).all()
    }
    variants = {
        v.id: v
        for v in (
            await db.scalars(select(ItemVariant).where(ItemVariant.id.in_(variant_ids)))
        ).all()
    } if variant_ids else {}
    add_ons = {
        a.id: a
        for a in (await db.scalars(select(ItemAddOn).where(ItemAddOn.id.in_(add_on_ids)))).all()
    } if add_on_ids else {}

    out: list[CartLineOut] = []
    quote_lines: list[QuoteLine] = []
    for line in sorted(cart.items, key=lambda i: i.created_at):
        item = items.get(line.menu_item_id)
        if item is None:
            # The dish was deleted out from under the cart. Skip it rather than
            # 500 — the customer sees it vanish, which is the truth.
            continue
        variant = variants.get(line.variant_id) if line.variant_id else None
        chosen = [add_ons[a.add_on_id] for a in line.add_ons if a.add_on_id in add_ons]

        unit_price = variant.price if variant else item.base_price
        add_ons_total = sum(a.price for a in chosen)
        available = (
            item.is_available
            and (variant is None or variant.is_available)
            and all(a.is_available for a in chosen)
        )

        out.append(
            CartLineOut(
                id=str(line.id),
                menu_item_id=str(item.id),
                name=item.name,
                image_url=item.image_url,
                quantity=line.quantity,
                variant_id=str(variant.id) if variant else None,
                variant_name=variant.name if variant else None,
                add_on_ids=[str(a.id) for a in chosen],
                add_on_names=[a.name for a in chosen],
                unit_price=to_major(unit_price),
                add_ons_total=to_major(add_ons_total),
                line_total=to_major((unit_price + add_ons_total) * line.quantity),
                notes=line.notes,
                is_available=available,
            )
        )
        quote_lines.append(
            QuoteLine(
                menu_item_id=str(item.id),
                name=item.name,
                quantity=line.quantity,
                unit_price=unit_price,
                add_ons_total=add_ons_total,
                image_url=item.image_url,
                variant_name=variant.name if variant else None,
                add_on_names=[a.name for a in chosen],
                notes=line.notes,
            )
        )
    return out, quote_lines


async def get_cart(db: AsyncSession, user_id: uuid.UUID) -> CartOut:
    """Spec #26. An absent cart is an empty cart, not a 404.

    The client renders Empty Cart either way, and making it branch on a status
    code for a state that is entirely normal would be needless.
    """
    cart = await _load_cart(db, user_id)
    if cart is None or not cart.items:
        return CartOut()

    restaurant = await db.get(Restaurant, cart.restaurant_id)
    lines, quote_lines = await _price_lines(db, cart)
    item_total = sum(q.line_total for q in quote_lines)
    minimum = restaurant.min_order_amount if restaurant else 0

    return CartOut(
        id=str(cart.id),
        restaurant_id=str(cart.restaurant_id),
        restaurant_name=restaurant.name if restaurant else None,
        restaurant_is_open=restaurant is not None
        and str(restaurant.status) == RestaurantStatus.OPEN,
        items=lines,
        item_total=to_major(item_total),
        item_count=sum(line.quantity for line in lines),
        min_order_amount=to_major(minimum),
        meets_minimum=item_total >= minimum,
    )


async def quote_lines_for(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[Cart | None, list[QuoteLine]]:
    """The pricing view of the cart, for checkout and order placement."""
    cart = await _load_cart(db, user_id)
    if cart is None or not cart.items:
        return cart, []
    _, quote_lines = await _price_lines(db, cart)
    return cart, quote_lines


async def modify_item(db: AsyncSession, user_id: uuid.UUID, body: CartItemRequest) -> CartOut:
    """Spec #27. Add, update or remove one configured line. `quantity: 0` removes.

    Decision D4: an item that HAS variants requires one to be chosen. Silently
    defaulting to the cheapest is how a customer ends up charged for a small
    when the screen said large.
    """
    menu_item_id = _as_uuid(body.menu_item_id, "menu_item_id")
    item = await db.scalar(
        select(MenuItem)
        .where(MenuItem.id == menu_item_id, MenuItem.deleted_at.is_(None))
        .options(selectinload(MenuItem.variants), selectinload(MenuItem.add_ons))
    )
    if item is None:
        raise NotFoundError("Menu item not found")

    variant = None
    if item.variants:
        if not body.variant_id:
            raise ValidationError(
                f"'{item.name}' requires a variant",
                details=[f"{v.name} ({v.id})" for v in item.variants],
            )
        variant_id = _as_uuid(body.variant_id, "variant_id")
        variant = next((v for v in item.variants if v.id == variant_id), None)
        if variant is None:
            raise ValidationError("That variant does not belong to this item")
    elif body.variant_id:
        raise ValidationError(f"'{item.name}' has no variants")

    valid_add_ons = {a.id for a in item.add_ons}
    requested = [_as_uuid(a, "add_on_ids") for a in body.add_on_ids]
    unknown = [a for a in requested if a not in valid_add_ons]
    if unknown:
        raise ValidationError(
            "Those add-ons do not belong to this item",
            details=[str(a) for a in unknown],
        )

    cart = await _load_cart(db, user_id)
    if cart is None:
        if body.quantity == 0:
            return CartOut()
        # `items=[]` initialises the collection explicitly. The relationship is
        # lazy="raise", so on a brand-new instance the attribute would otherwise
        # try to emit a load and raise instead of yielding the empty list it
        # obviously is.
        cart = Cart(user_id=user_id, restaurant_id=item.restaurant_id, items=[])
        db.add(cart)
        await db.flush()
    elif cart.restaurant_id != item.restaurant_id:
        # The database would refuse this anyway; this is the courteous version.
        current = await db.get(Restaurant, cart.restaurant_id)
        raise ConflictError(
            "Your cart already has items from another restaurant",
            details=[
                f"Cart: {current.name if current else 'another restaurant'}",
                "Empty the cart before ordering from somewhere else.",
            ],
        )

    fingerprint = _fingerprint(requested)
    existing = next(
        (
            line
            for line in cart.items
            if line.menu_item_id == item.id
            and line.variant_id == (variant.id if variant else None)
            and line.add_ons_fingerprint == fingerprint
        ),
        None,
    )

    if body.quantity == 0:
        if existing is not None:
            await db.delete(existing)
            await db.flush()
            # An empty cart is deleted rather than kept as a husk pointing at a
            # restaurant — otherwise the next add from elsewhere hits the
            # cross-restaurant 409 for a cart with nothing in it.
            remaining = await db.scalar(
                select(func.count()).select_from(CartItem).where(CartItem.cart_id == cart.id)
            )
            if not remaining:
                # Core DELETE rather than db.delete(cart): the ORM cascade would
                # re-issue a delete for the line we just removed, which matches
                # zero rows and warns. `fk_cart_items_cart` is ON DELETE CASCADE,
                # so the database clears any children itself.
                await db.execute(delete(Cart).where(Cart.id == cart.id))
                await db.flush()
                return CartOut()
        return await get_cart(db, user_id)

    if existing is not None:
        existing.quantity = body.quantity
        existing.notes = body.notes
        # Must be flushed before the re-read below: `_load_cart` uses
        # populate_existing, which refreshes the instance FROM the database and
        # would otherwise discard this change and echo back the old quantity.
        await db.flush()
    else:
        line = CartItem(
            cart_id=cart.id,
            restaurant_id=item.restaurant_id,
            menu_item_id=item.id,
            variant_id=variant.id if variant else None,
            quantity=body.quantity,
            add_ons_fingerprint=fingerprint,
            notes=body.notes,
        )
        db.add(line)
        await db.flush()
        for add_on_id in requested:
            db.add(
                CartItemAddOn(
                    cart_item_id=line.id, add_on_id=add_on_id, menu_item_id=item.id
                )
            )
        await db.flush()

    return await get_cart(db, user_id)


async def clear(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Empty the cart. Called after an order is placed (spec #29)."""
    cart = await db.scalar(select(Cart).where(Cart.user_id == user_id))
    if cart is not None:
        await db.execute(delete(Cart).where(Cart.id == cart.id))


__all__ = ["clear", "get_cart", "modify_item", "quote_lines_for"]
