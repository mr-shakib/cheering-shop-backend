"""Vendor Operations — spec endpoints #36–37, #39–46, plus [EXTENDED] routes.

Every handler here takes `restaurant: VendorRestaurant` rather than querying
`owner_id`. That is decision D1's hedge: resolution is concentrated in one
dependency, so supporting multi-outlet vendors later costs one migration and one
function body instead of rewriting ten endpoints. For the same reason every
response echoes `restaurant_id`, so clients already carry it when that day comes.

**Nothing in this module accepts a restaurant id from the caller.** Ownership
comes from the token, via the dependency; a menu item or order id that belongs
to someone else resolves to 404, never 403 — a vendor should not be able to
confirm that another vendor's records exist.

Registration order follows the router's convention: literal segments before
`{param}` routes, so `/menu/categories` can never be swallowed by `/menu/{id}`.

**[EXTENDED] endpoints.** The spec's twelve vendor routes cannot run a
restaurant on their own: they define `POST /vendor/menu/items` but nothing that
creates the category it requires, no way to edit or remove an item once created,
no way to change anything about the storefront after registration, and no way to
read an order in the queue. Those gaps are filled below and are marked
individually.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DbSession, Paginated, VendorRestaurant, VendorUser
from app.core.responses import ok, paginated
from app.schemas.requests import (
    BusinessHoursRequest,
    HandoffRequest,
    MenuCategoryCreateRequest,
    MenuCategoryUpdateRequest,
    MenuItemCreateRequest,
    MenuItemStatusRequest,
    MenuItemUpdateRequest,
    MenuReorderRequest,
    OrderRejectRequest,
    PayoutCreateRequest,
    PromotionCreateRequest,
    PromotionUpdateRequest,
    RestaurantProfileUpdateRequest,
    StoreStatusRequest,
)
from app.services import (
    menu_service,
    vendor_finance_service,
    vendor_insights_service,
    vendor_order_service,
    vendor_promotion_service,
    vendor_service,
)

router = APIRouter(prefix="/vendor", tags=["Vendor"])


# ---------------------------------------------------------------------------
# Storefront
# ---------------------------------------------------------------------------


@router.get("/profile", summary="Get my restaurant [EXTENDED]")
async def get_profile(restaurant: VendorRestaurant, user: VendorUser):
    """**[EXTENDED]** — the owner's view of their own storefront.

    Needed as its own endpoint because the public `GET /restaurants/{id}` filters
    on `is_active AND is_verified`: between registering and being approved, a
    vendor could not fetch their own restaurant from anywhere in the API. It
    also carries owner-only settings (commission rate, verification state) that
    the public payload has no business exposing.
    """
    _ = user
    return ok(vendor_service.to_profile(restaurant).model_dump())


@router.patch("/profile", summary="Update my restaurant [EXTENDED]")
async def update_profile(
    body: RestaurantProfileUpdateRequest, restaurant: VendorRestaurant, db: DbSession
):
    """**[EXTENDED]** — edit the storefront.

    Registration was the only write to a restaurant row, so nothing set there
    could ever be corrected: no logo, no delivery fee, not even a typo in the
    address.

    PATCH, so an omitted field is left alone and an explicit `null` clears it.
    `slug`, `is_verified`, `is_active` and `commission_rate` are rejected rather
    than ignored — see the request model for why each one is off limits.
    """
    profile = await vendor_service.update_profile(db, restaurant, body)
    await db.commit()
    return ok(profile.model_dump())


@router.patch("/store/status", summary="Open or close the store")
async def set_store_status(body: StoreStatusRequest, restaurant: VendorRestaurant, db: DbSession):
    """Spec #36.

    Setting OPEN on an unapproved restaurant is accepted and has no effect;
    `is_accepting_orders` in the response is the honest answer, and the message
    names whichever switch is still off. There are no scheduled opening hours —
    this is a manual toggle and nothing closes the store on the vendor's behalf.
    """
    result = await vendor_service.set_store_status(db, restaurant, body.status)
    await db.commit()
    return ok(result.model_dump())


# ---------------------------------------------------------------------------
# Menu — categories
# ---------------------------------------------------------------------------


@router.get("/menu", summary="My full menu [EXTENDED]")
async def get_menu(restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — the whole menu tree, nothing filtered out.

    The public `GET /restaurants/{id}/menu` hides inactive categories and
    unavailable items, which is right for a customer and useless for the owner:
    an item hidden because it sold out would disappear from the very screen used
    to put it back.
    """
    menu = await menu_service.get_menu(db, restaurant)
    return ok(menu.model_dump())


@router.get("/menu/categories", summary="List menu categories")
async def list_categories(
    restaurant: VendorRestaurant,
    db: DbSession,
    include_inactive: Annotated[bool, Query()] = True,
):
    """Spec #44. Includes inactive categories by default — this is the owner's
    view, and a category they cannot see is one they cannot reactivate."""
    categories = await menu_service.list_categories(db, restaurant, include_inactive)
    return ok([c.model_dump() for c in categories])


@router.post(
    "/menu/categories",
    status_code=status.HTTP_201_CREATED,
    summary="Create a menu category [EXTENDED]",
)
async def create_category(
    body: MenuCategoryCreateRequest, restaurant: VendorRestaurant, db: DbSession
):
    """**[EXTENDED]** — the endpoint that makes menu building possible at all.

    The spec lists `GET /vendor/menu/categories` and `POST /vendor/menu/items`,
    but item creation requires a `category_id` and no endpoint produced one. An
    approved vendor could not add a single dish.
    """
    category = await menu_service.create_category(db, restaurant, body)
    await db.commit()
    return ok(category.model_dump())


@router.patch("/menu/categories/{category_id}", summary="Update a category [EXTENDED]")
async def update_category(
    category_id: uuid.UUID,
    body: MenuCategoryUpdateRequest,
    restaurant: VendorRestaurant,
    db: DbSession,
):
    """**[EXTENDED]** — rename, reorder, or deactivate a category.

    Deactivating hides the category and everything in it from customers while
    leaving the items intact, which is the reversible alternative to deletion.
    """
    category = await menu_service.update_category(db, restaurant, category_id, body)
    await db.commit()
    return ok(category.model_dump())


@router.delete("/menu/categories/{category_id}", summary="Delete a category [EXTENDED]")
async def delete_category(category_id: uuid.UUID, restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — delete an empty category.

    Returns 409 while it still holds items. `fk_menu_items_category` is
    ON DELETE CASCADE, so allowing this would destroy every item underneath —
    including the rows order history and analytics point at. Move the items, or
    deactivate the category instead.
    """
    await menu_service.delete_category(db, restaurant, category_id)
    await db.commit()
    return ok({"message": "Category deleted", "restaurant_id": str(restaurant.id)})


@router.patch("/menu/reorder", summary="Reorder categories and items [EXTENDED]")
async def reorder_menu(body: MenuReorderRequest, restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — apply a drag-and-drop reorder.

    Four tables carry a `sort_order` column that no endpoint could write, so
    menus were stuck in creation order. Categories and items move in one
    request because reordering a menu is one gesture, and every id is validated
    before anything is written — a payload with one foreign id changes nothing
    rather than applying half of itself.
    """
    result = await menu_service.reorder(db, restaurant, body)
    await db.commit()
    return ok({**result, "restaurant_id": str(restaurant.id)})


# ---------------------------------------------------------------------------
# Menu — items
# ---------------------------------------------------------------------------


@router.post("/menu/items", status_code=status.HTTP_201_CREATED, summary="Create a menu item")
async def create_menu_item(
    body: MenuItemCreateRequest, restaurant: VendorRestaurant, db: DbSession
):
    """Spec #45. Item, variants and add-ons in one transaction.

    The composite FK to `menu_categories` guarantees the category belongs to
    this vendor's restaurant — a forged `category_id` cannot smuggle an item
    onto someone else's menu even if the check in the service were removed.

    All or nothing: an item whose variants failed to save would sell at its
    `base_price`, which decision D4 says is a display price only.
    """
    item = await menu_service.create_item(db, restaurant, body)
    await db.commit()
    return ok(item.model_dump())


@router.get("/menu/items/{item_id}", summary="Get a menu item [EXTENDED]")
async def get_menu_item(item_id: uuid.UUID, restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — read one item with its variants and add-ons, for the
    edit screen. Creating an item returned its id and nothing could fetch it
    back."""
    item = await menu_service.get_item(db, restaurant, item_id)
    return ok(item.model_dump())


@router.patch("/menu/items/{item_id}", summary="Update a menu item [EXTENDED]")
async def update_menu_item(
    item_id: uuid.UUID,
    body: MenuItemUpdateRequest,
    restaurant: VendorRestaurant,
    db: DbSession,
):
    """**[EXTENDED]** — edit an item.

    Items could be created and toggled available, but never repriced, renamed,
    re-photographed or moved between categories.

    `variants` and `add_ons` are replace-sets when present: send a variant's
    `id` to edit it in place, omit the id to add one, and leave it out of the
    list to delete it. Editing in place matters because deleting a variant
    cascades into every cart holding it — a price change should not empty
    anyone's basket.
    """
    item = await menu_service.update_item(db, restaurant, item_id, body)
    await db.commit()
    return ok(item.model_dump())


@router.delete("/menu/items/{item_id}", summary="Delete a menu item [EXTENDED]")
async def delete_menu_item(item_id: uuid.UUID, restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — remove an item from the menu.

    A soft delete: `deleted_at` is stamped and the row stays. Order history and
    the analytics `top_items` figures are keyed on `menu_item_id`, so a hard
    delete would quietly restate past months. The column has existed since the
    first migration; this is the first endpoint to write it.
    """
    await menu_service.delete_item(db, restaurant, item_id)
    await db.commit()
    return ok({"message": "Menu item deleted", "restaurant_id": str(restaurant.id)})


@router.patch("/menu/items/{item_id}/status", summary="Toggle item availability")
async def set_menu_item_status(
    item_id: uuid.UUID,
    body: MenuItemStatusRequest,
    restaurant: VendorRestaurant,
    db: DbSession,
):
    """Spec #46. The high-frequency 'sold out' toggle.

    Kept separate from PATCH `/menu/items/{id}` deliberately: it is pressed
    dozens of times a service from a list screen holding no other state, and a
    one-field body is the difference between a tap that survives a bad
    connection and one that does not.
    """
    item = await menu_service.set_item_status(db, restaurant, item_id, body.is_available)
    await db.commit()
    return ok(item.model_dump())


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@router.get("/orders", summary="Incoming order queue")
async def list_vendor_orders(
    restaurant: VendorRestaurant,
    db: DbSession,
    page: Paginated,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description="One status, a comma-separated list, or ACTIVE for "
            "PENDING+PREPARING+READY",
        ),
    ] = None,
):
    """Spec #37. Newest first, served by
    `ix_orders_vendor_queue (restaurant_id, status, placed_at DESC)`.

    Rows carry a line count but not the lines themselves — the queue is polled
    and pushed constantly, and `GET /vendor/orders/{id}` exists for the moment
    a vendor actually starts cooking.
    """
    statuses = vendor_order_service.parse_status_filter(status_filter)
    orders, total = await vendor_order_service.list_orders(
        db, restaurant, page.limit, page.offset, statuses
    )
    return paginated(
        [o.model_dump() for o in orders], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/orders/{order_id}", summary="Order detail [EXTENDED]")
async def get_vendor_order(order_id: uuid.UUID, restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — what the kitchen needs to actually cook the order.

    The spec defines a queue and no way to read a row of it: a vendor could see
    that an order existed but not its items, chosen variants, add-ons or notes.
    Every field is the snapshot taken at purchase time, so repricing the menu
    never rewrites an order already placed.
    """
    detail = await vendor_order_service.get_order_detail(db, restaurant, order_id)
    return ok(detail.model_dump())


@router.post("/orders/{order_id}/accept", summary="Accept an order")
async def accept_order(
    order_id: uuid.UUID, restaurant: VendorRestaurant, db: DbSession, user: VendorUser
):
    """Spec #39. PENDING -> PREPARING, and cancels the auto-decline.

    Clearing `auto_decline_at` is what cancels it: the sweeper's partial index is
    `WHERE status = 'PENDING' AND auto_decline_at IS NOT NULL`, so the order
    stops being a candidate immediately. No task handle to chase, and a worker
    restart cannot resurrect the timeout.
    """
    summary = await vendor_order_service.accept_order(db, restaurant, order_id, user)
    await db.commit()
    return ok(summary.model_dump())


@router.post("/orders/{order_id}/reject", summary="Reject an order")
async def reject_order(
    order_id: uuid.UUID,
    body: OrderRejectRequest,
    restaurant: VendorRestaurant,
    db: DbSession,
    user: VendorUser,
):
    """Spec #40. Cancels the order and marks it for refund.

    **Spec §12 Q3 left the rebooking policy open.** This implements
    refund-and-notify rather than silent re-placement with a nearby vendor: a
    substitute restaurant has different prices, a different menu and a different
    delivery time, so recreating "the same order" means deciding on the
    customer's behalf what they will pay and wait for. Discovery already gives
    the client what it needs to offer alternatives.

    Allowed while PENDING or PREPARING only. Refunds are recorded, not executed —
    no payment gateway is connected yet.
    """
    summary = await vendor_order_service.reject_order(db, restaurant, order_id, user, body.reason)
    await db.commit()
    return ok(summary.model_dump())


@router.post("/orders/{order_id}/ready", summary="Mark order ready")
async def mark_ready(
    order_id: uuid.UUID, restaurant: VendorRestaurant, db: DbSession, user: VendorUser
):
    """Spec #41. PREPARING -> READY.

    Decision D3 (amended): the rider PIN is generated and HMAC'd here — not at
    order creation, so it does not exist during the whole cooking window.

    `handoff_code` in the response is what the handoff screen shows ("Hand
    this code to your rider"). It stays readable via `GET /vendor/orders/{id}`
    while the order is READY, so an app restart cannot strand a pickup. See
    the service docstring for why the code is vendor-visible until the rider
    app exists to receive it instead.
    """
    summary, pin = await vendor_order_service.mark_ready(db, restaurant, order_id, user)
    await db.commit()
    payload = summary.model_dump()
    payload["handoff_code"] = pin
    return ok(payload)


@router.post("/orders/{order_id}/handoff", summary="Verify rider PIN and hand off")
async def handoff_order(
    order_id: uuid.UUID,
    body: HandoffRequest,
    restaurant: VendorRestaurant,
    db: DbSession,
    user: VendorUser,
):
    """Spec #42. READY -> PICKED_UP. Returns 400 on an invalid PIN.

    Constant-time HMAC comparison with an attempt counter — the counter is what
    actually protects a 4-digit space, since 10,000 candidates fall to brute
    force regardless of how the digest is computed. After
    `HANDOFF_MAX_ATTEMPTS` failures the PIN is dead and the order must be marked
    ready again to issue a new one.

    Also 409s when no rider has been assigned yet: `ck_orders_rider_required`
    forbids a PICKED_UP order without one, and an explanation beats a constraint
    violation.
    """
    result = await vendor_order_service.handoff_order(
        db, restaurant, order_id, user, body.rider_pin
    )
    await db.commit()
    return ok(result.model_dump())


# ---------------------------------------------------------------------------
# Analytics & reviews
# ---------------------------------------------------------------------------


@router.get("/analytics", summary="Earnings dashboard")
async def vendor_analytics(
    restaurant: VendorRestaurant,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Spec #43. Served by the partial index
    `ix_orders_analytics (restaurant_id, delivered_at) WHERE status = 'DELIVERED'`.

    Defaults to the last 30 days. Counts DELIVERED orders only — an in-flight or
    cancelled order is not revenue, and including it would make this dashboard
    disagree with every payout the vendor receives. Cancellations still show up
    in `status_breakdown`.

    Earnings use the per-order `commission_amount` snapshot, never the live
    `restaurants.commission_rate` — otherwise changing a vendor's rate would
    retroactively rewrite historical earnings (decision D6).
    """
    result = await vendor_insights_service.analytics(db, restaurant, date_from, date_to)
    return ok(result.model_dump())


@router.get("/reviews", summary="Customer reviews [EXTENDED]")
async def vendor_reviews(restaurant: VendorRestaurant, db: DbSession, page: Paginated):
    """**[EXTENDED]** — what customers said, newest first.

    `restaurants.rating_avg` is a single number with no way to see what produced
    it. Only the restaurant rating and comment are returned: `rider_rating`
    grades the delivery, and showing a vendor a score they cannot influence
    invites complaints they cannot act on.
    """
    reviews, total = await vendor_insights_service.list_reviews(
        db, restaurant, page.limit, page.offset
    )
    return paginated(
        [r.model_dump() for r in reviews], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/reviews/summary", summary="Rating histogram [EXTENDED]")
async def vendor_reviews_summary(restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — the Feedback header: average, count, and the star
    bars. Recomputed from the review rows so the bars always sum to the count
    shown beside them."""
    summary = await vendor_insights_service.reviews_summary(db, restaurant)
    return ok(summary.model_dump())


# ---------------------------------------------------------------------------
# Dashboard & performance
# ---------------------------------------------------------------------------


@router.get("/dashboard", summary="Home & Overview in one call [EXTENDED]")
async def vendor_dashboard(restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — everything the app's two landing tabs render: queue
    counts for the Order tab's chips, today's delivered orders and earnings,
    the last-7-days chart, acceptance rate and the five most recent orders.

    Exists because those tabs are the app's resting screen: rendering them
    from five separate endpoints would turn every app-resume into five round
    trips on a kitchen tablet's connection.
    """
    result = await vendor_insights_service.dashboard(db, restaurant)
    return ok(result.model_dump())


@router.get("/performance", summary="Performance & ratings [EXTENDED]")
async def vendor_performance(
    restaurant: VendorRestaurant,
    db: DbSession,
    window_days: Annotated[int, Query(ge=7, le=90)] = 30,
):
    """**[EXTENDED]** — acceptance rate, on-time rate, rating, rejections this
    week. Rates are null until there is data — a new vendor has not failed at
    anything, and rendering 0% would say otherwise."""
    result = await vendor_insights_service.performance(db, restaurant, window_days)
    return ok(result.model_dump())


@router.get("/reports/csv", summary="Download report as CSV [EXTENDED]")
async def vendor_report_csv(
    restaurant: VendorRestaurant,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """**[EXTENDED]** — the Report screen's "All CSV Download". One row per
    DELIVERED order in the window (default: last 30 days), same population as
    `/vendor/analytics`, so the spreadsheet reconciles with the tiles.

    Plain `text/csv`, not the JSON envelope — this response is a file.
    """
    filename, body = await vendor_insights_service.report_csv(db, restaurant, date_from, date_to)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Earnings & payouts
# ---------------------------------------------------------------------------


@router.get("/earnings", summary="Balance and recent credits [EXTENDED]")
async def vendor_earnings(restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — the Earnings & payouts screen: available balance,
    lifetime totals, and the recent per-order credits.

    The balance is derived (delivered earnings minus non-failed payouts),
    never stored, so it cannot disagree with the payout history below it.
    """
    result = await vendor_finance_service.earnings(db, restaurant)
    return ok(result.model_dump())


@router.get("/payouts", summary="Payout history [EXTENDED]")
async def list_payouts(restaurant: VendorRestaurant, db: DbSession, page: Paginated):
    """**[EXTENDED]** — every withdrawal, newest first, with its status."""
    payouts, total = await vendor_finance_service.list_payouts(
        db, restaurant, page.limit, page.offset
    )
    return paginated(
        [vendor_finance_service.to_out(p).model_dump() for p in payouts],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/payouts", status_code=status.HTTP_201_CREATED, summary="Withdraw money [EXTENDED]")
async def request_payout(
    body: PayoutCreateRequest, restaurant: VendorRestaurant, db: DbSession
):
    """**[EXTENDED]** — the Withdraw Money button.

    Checks the balance under a row lock (two simultaneous taps cannot both
    pass), records the payout as PROCESSING and returns the receipt fields the
    success screen shows. No gateway is connected: a person executes the
    transfer and confirms it, which is when status becomes COMPLETED — or
    FAILED, which returns the amount to the balance automatically.
    """
    payout = await vendor_finance_service.request_payout(db, restaurant, body)
    await db.commit()
    return ok(
        {
            **vendor_finance_service.to_out(payout).model_dump(),
            "message": "Payout requested — the amount will arrive shortly",
        }
    )


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------


@router.get("/promotions", summary="My promotions [EXTENDED]")
async def list_promotions(restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — every offer with its live stats (redemptions, spend
    against budget). Unpaginated: a storefront runs a handful of offers."""
    promotions = await vendor_promotion_service.list_promotions(db, restaurant)
    return ok([p.model_dump() for p in promotions])


@router.post("/promotions", status_code=status.HTTP_201_CREATED, summary="Launch [EXTENDED]")
async def create_promotion(
    body: PromotionCreateRequest, restaurant: VendorRestaurant, db: DbSession
):
    """**[EXTENDED]** — the New Promotion form. Percentage, flat amount or
    free delivery; optional item scoping, schedule and budget cap.

    Customers cannot redeem anything until the checkout module ships — the
    offer is stored and reported now so the app can build against the final
    contract, and goes live the moment checkout does.
    """
    promo = await vendor_promotion_service.create(db, restaurant, body)
    await db.commit()
    return ok(vendor_promotion_service.to_out(promo, 0, 0, 0).model_dump())


@router.get("/promotions/{promotion_id}", summary="Promotion detail [EXTENDED]")
async def get_promotion(
    promotion_id: uuid.UUID, restaurant: VendorRestaurant, db: DbSession
):
    """**[EXTENDED]** — the detail screen: stats plus the 7-day redemptions
    chart. Someone else's promotion id is a 404, never a 403."""
    detail = await vendor_promotion_service.get_detail(db, restaurant, promotion_id)
    return ok(detail.model_dump())


@router.patch("/promotions/{promotion_id}", summary="Pause / resume / end [EXTENDED]")
async def update_promotion(
    promotion_id: uuid.UUID,
    body: PromotionUpdateRequest,
    restaurant: VendorRestaurant,
    db: DbSession,
):
    """**[EXTENDED]** — `is_active` pauses and resumes; `end_now: true` ends
    the offer permanently. Nothing else about a live promotion can change —
    repricing an offer customers have already seen is a bait-and-switch."""
    promo = await vendor_promotion_service.update(db, restaurant, promotion_id, body)
    await db.commit()
    stats = await vendor_promotion_service._stats(db, [promo.id])
    return ok(
        vendor_promotion_service.to_out(promo, *stats.get(promo.id, (0, 0, 0))).model_dump()
    )


# ---------------------------------------------------------------------------
# Business hours
# ---------------------------------------------------------------------------


@router.get("/hours", summary="Business hours [EXTENDED]")
async def get_hours(restaurant: VendorRestaurant):
    """**[EXTENDED]** — the weekly schedule. `is_configured: false` until the
    vendor first saves; the seven default rows are a template, not a claim."""
    return ok(vendor_service.hours_out(restaurant).model_dump())


@router.put("/hours", summary="Set business hours [EXTENDED]")
async def set_hours(body: BusinessHoursRequest, restaurant: VendorRestaurant, db: DbSession):
    """**[EXTENDED]** — replace the whole week at once (the screen saves all
    seven days).

    **Informational.** Customers see these hours, but nothing opens or closes
    the store from them — there is no scheduler, and `PATCH /store/status`
    remains the only real switch. Saving Sunday as closed does not close the
    store on Sunday.
    """
    result = await vendor_service.set_hours(db, restaurant, body)
    await db.commit()
    return ok(result.model_dump())
