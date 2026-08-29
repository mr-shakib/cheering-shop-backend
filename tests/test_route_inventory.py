"""Spec conformance: every endpoint in §5's table must exist, and nothing else.

This is transcribed directly from the specification's Endpoint Summary Table
(rows 1–47). It is the check that stops the API drifting away from the document
as modules land in Step 4 — a renamed path or a forgotten endpoint fails here.
"""

from app.main import app

# (method, path) exactly as specified in §5, with the /api/v1 prefix applied.
# FastAPI renders path params as {name}; the spec writes {id}, so names are
# normalised below before comparison.
SPEC_ENDPOINTS: list[tuple[int, str, str]] = [
    (1, "POST", "/auth/otp/send"),
    (2, "POST", "/auth/otp/verify"),
    (3, "POST", "/auth/login"),
    (4, "POST", "/auth/login/2fa"),
    (5, "POST", "/auth/password/forgot"),
    (6, "POST", "/auth/password/reset"),
    (7, "POST", "/auth/biometrics/enable"),
    (8, "DELETE", "/auth/biometrics/disable"),
    (9, "GET", "/users/me/security"),
    (10, "POST", "/auth/2fa/generate"),
    (11, "POST", "/auth/2fa/enable"),
    (12, "POST", "/auth/2fa/disable"),
    (13, "PUT", "/users/me/profile"),
    (14, "GET", "/users/me/addresses"),
    (15, "POST", "/users/me/addresses"),
    (16, "PUT", "/users/me/addresses/{id}"),
    (17, "DELETE", "/users/me/addresses/{id}"),
    (18, "PATCH", "/users/me/addresses/{id}/default"),
    (19, "GET", "/home/feed"),
    (20, "GET", "/restaurants"),
    (21, "GET", "/restaurants/{id}"),
    (22, "GET", "/restaurants/{id}/menu"),
    (23, "GET", "/search"),
    (24, "GET", "/users/me/favorites"),
    (25, "POST", "/users/me/favorites/{id}"),
    (26, "GET", "/cart"),
    (27, "POST", "/cart/items"),
    (28, "GET", "/checkout/summary"),
    (29, "POST", "/orders"),
    (30, "POST", "/orders/{id}/cancel"),
    (31, "GET", "/orders"),
    (32, "GET", "/orders/{id}/tracking"),
    (33, "WS", "/ws/orders/{id}/live-tracking"),
    (34, "POST", "/orders/{id}/call"),
    (35, "POST", "/orders/{id}/reviews"),
    (36, "PATCH", "/vendor/store/status"),
    (37, "GET", "/vendor/orders"),
    (38, "WS", "/ws/vendor/live"),
    (39, "POST", "/vendor/orders/{id}/accept"),
    (40, "POST", "/vendor/orders/{id}/reject"),
    (41, "POST", "/vendor/orders/{id}/ready"),
    (42, "POST", "/vendor/orders/{id}/handoff"),
    (43, "GET", "/vendor/analytics"),
    (44, "GET", "/vendor/menu/categories"),
    (45, "POST", "/vendor/menu/items"),
    (46, "PATCH", "/vendor/menu/items/{id}/status"),
    (47, "POST", "/uploads/presigned-url"),
]

# Endpoints this codebase adds because the spec needs them to function.
# Kept as a SEPARATE list so "does the API still match the spec?" and "what have
# we added?" remain two different questions with two different answers.
EXTENDED_ENDPOINTS: list[tuple[str, str, str]] = [
    (
        "POST",
        "/auth/refresh",
        "Spec §1 mandates an access/refresh pair but §3 defines no endpoint to "
        "redeem one. Without this, every user is logged out when their access "
        "token expires and must re-enter their password.",
    ),
    (
        "POST",
        "/auth/logout",
        "Spec §1 mandates refresh tokens but defines no way to revoke one. "
        "Without this, tapping 'log out' only clears local storage while the "
        "refresh token stays valid for 30 days on a stolen device.",
    ),
    (
        "GET",
        "/users/me",
        "A mobile client restoring a saved token needs to resolve who it "
        "belongs to before rendering. Decoding the JWT client-side cannot "
        "reveal whether the profile changed since the token was issued.",
    ),
    (
        "POST",
        "/auth/biometrics/challenge",
        "Spec #7/#8 enrol and un-enrol a device key but define no endpoint "
        "that uses it, so biometric enrolment wrote a key nothing could read. "
        "This issues the nonce the device signs.",
    ),
    (
        "POST",
        "/auth/biometrics/login",
        "The other half of biometric login: verifies the signed challenge "
        "against the enrolled public key and issues a session. Without it the "
        "entire biometrics feature is inert.",
    ),
    (
        "POST",
        "/auth/register/vendor",
        "The spec defines a VENDOR role and a permission matrix but every "
        "signup path it describes creates a CUSTOMER, so there was no way to "
        "create a vendor account at all — the vendor app had no front door.",
    ),
    (
        "GET",
        "/admin/restaurants/pending",
        "Vendor registration is gated on approval; without a queue an "
        "administrator cannot see who is waiting.",
    ),
    (
        "POST",
        "/admin/restaurants/{id}/verify",
        "The other half of the approval gate. Without it a registered vendor "
        "waits forever and can never appear in customer discovery.",
    ),
    (
        "PATCH",
        "/admin/restaurants/{id}/commission",
        "The only way to price a restaurant. Approval asks for no rate and the "
        "vendor is refused the field on their own profile, so renegotiating a "
        "commission otherwise means hand-written SQL against production.",
    ),
    (
        "POST",
        "/users/me/password",
        "The spec only offers password reset via OTP. A signed-in user "
        "changing their own password should not have to pretend they forgot "
        "it, and doing so would consume an OTP send for no reason.",
    ),
    # --- Vendor partner applications ---------------------------------------
    # The partner app's registration flow (business info → location → owner →
    # documents → review) needs an application record an administrator can
    # review; POST /auth/register/vendor creates the account but throws the
    # form away.
    (
        "POST",
        "/vendor/applications",
        "The application form collects business type, category, NID, area, "
        "documents and payout details — none of which registration could "
        "accept, so the admin approved storefronts with nothing to review.",
    ),
    (
        "GET",
        "/vendor/applications/{id}",
        "The success screen promises a decision in 2-3 business days; without "
        "a status endpoint the applicant's only option is to email support "
        "with their reference number.",
    ),
    (
        "POST",
        "/vendor/applications/uploads",
        "POST /uploads/presigned-url requires a session and an applicant has "
        "no account yet, so the Document step of the form had no way to "
        "upload the NID, shop photo or trade licence it asks for.",
    ),
    (
        "GET",
        "/orders/{id}",
        "Spec #30 lists order history but no way to open one. The Order "
        "Details screen needs the receipt, the line items and the status "
        "timeline, none of which fit in a history row.",
    ),
    (
        "GET",
        "/restaurants/{id}/schedule",
        "The Schedule Order sheet offers delivery windows days ahead. Slots "
        "are generated from business hours rather than stored, so the client "
        "needs an endpoint to ask what is bookable — guessing them locally "
        "would drift from the lead time the server enforces at placement.",
    ),
    (
        "GET",
        "/orders/{id}/messages",
        "The Message screen. The spec has a masked phone call but no text "
        "channel, and a rider who cannot find a gate has nothing to type "
        "into.",
    ),
    (
        "POST",
        "/orders/{id}/messages",
        "The other half of the chat: sending. Scoped to the order so the "
        "channel closes with it — a standing line to a stranger's device "
        "after delivery is a safety problem, not a feature.",
    ),
    (
        "GET",
        "/admin/vendor-applications",
        "The review queue. /admin/restaurants/pending lists storefronts but "
        "not the identity, documents or payout details a decision needs.",
    ),
    (
        "GET",
        "/admin/vendor-applications/{id}",
        "The screen a decision is made on: everything the form submitted, "
        "including NID, document URLs and payout account.",
    ),
    (
        "POST",
        "/admin/vendor-applications/{id}/approve",
        "Approving must do three things at once — mark the application, "
        "verify the restaurant, and email the owner their sign-in steps — or "
        "an approved vendor is never told they can sell.",
    ),
    (
        "POST",
        "/admin/vendor-applications/{id}/reject",
        "The other half of the decision. Records the reason and emails it to "
        "the applicant; without it a rejected application just sits PENDING "
        "forever.",
    ),
    # --- Vendor operations -------------------------------------------------
    # The spec's twelve vendor routes cannot run a restaurant on their own.
    # These close the gaps; each one names the specific thing that was
    # impossible without it.
    (
        "GET",
        "/vendor/profile",
        "The public GET /restaurants/{id} filters on is_active AND is_verified, "
        "so between registering and being approved a vendor could not read "
        "their own restaurant from anywhere in the API.",
    ),
    (
        "PATCH",
        "/vendor/profile",
        "Registration was the only write to a restaurant row, so nothing set "
        "there could ever be changed: no logo, no delivery fee, no minimum "
        "order, not even a typo in the address.",
    ),
    (
        "GET",
        "/vendor/menu",
        "The public menu endpoint hides inactive categories and unavailable "
        "items, so an item switched off because it sold out vanished from the "
        "very screen the vendor needs to switch it back on.",
    ),
    (
        "POST",
        "/vendor/menu/categories",
        "POST /vendor/menu/items requires a category_id and no endpoint in the "
        "spec produced one, so an approved vendor could not add a single dish "
        "to their menu. This is the hard blocker.",
    ),
    (
        "PATCH",
        "/vendor/menu/categories/{id}",
        "Categories could be created and never renamed, reordered or "
        "deactivated. Deactivating is also the only reversible alternative to "
        "a delete that cascades into every item.",
    ),
    (
        "DELETE",
        "/vendor/menu/categories/{id}",
        "A menu accumulates seasonal sections that have to go somewhere. "
        "Refuses while the category still holds items, because the cascade "
        "would destroy rows that order history points at.",
    ),
    (
        "PATCH",
        "/vendor/menu/reorder",
        "Four tables carry a sort_order column that no endpoint could write, "
        "so menus were frozen in creation order and a vendor could not put "
        "their signature dish at the top.",
    ),
    (
        "GET",
        "/vendor/menu/items/{id}",
        "Creating an item returned its id and nothing could read it back, so "
        "an edit screen had no way to load the item it was editing.",
    ),
    (
        "PATCH",
        "/vendor/menu/items/{id}",
        "Items could be created and toggled available, but never repriced, "
        "renamed, re-photographed or moved between categories — a menu that "
        "was write-once in everything but availability.",
    ),
    (
        "DELETE",
        "/vendor/menu/items/{id}",
        "Nothing could remove a dish. menu_items.deleted_at existed from the "
        "first migration with no endpoint to write it, so discontinued items "
        "stayed on the menu permanently.",
    ),
    (
        "POST",
        "/vendor/menu/items/{id}/variants",
        "Adding one size meant PATCHing the item with every other size echoed "
        "back by id, because the collection is a replace-set — and a client "
        "that got that list wrong deleted the options it forgot.",
    ),
    (
        "PATCH",
        "/vendor/menu/items/{id}/variants/{variant_id}",
        "Editing one variant meant resending the whole set, so 'change the "
        "price of Large' and 'delete every other size' were the same request "
        "with one field forgotten.",
    ),
    (
        "DELETE",
        "/vendor/menu/items/{id}/variants/{variant_id}",
        "The only way to remove a variant was to omit it from a replace-set, "
        "which made deletion a side effect of a save rather than a thing a "
        "vendor could ask for.",
    ),
    (
        "POST",
        "/vendor/menu/items/{id}/add-ons",
        "Same replace-set problem as variants: an 'add extra' button had to "
        "resend the whole add-on list to add one row.",
    ),
    (
        "PATCH",
        "/vendor/menu/items/{id}/add-ons/{add_on_id}",
        "Same as variants: repricing one extra required rewriting the set it "
        "belonged to.",
    ),
    (
        "DELETE",
        "/vendor/menu/items/{id}/add-ons/{add_on_id}",
        "Same as variants — removing one extra required rewriting the set it "
        "belonged to.",
    ),
    (
        "GET",
        "/vendor/orders/{id}",
        "The spec defines a queue and no way to read a row of it: a vendor "
        "could see that an order existed but not its items, chosen variants, "
        "add-ons or notes, which is everything needed to cook it.",
    ),
    (
        "GET",
        "/vendor/reviews",
        "restaurants.rating_avg is a single number with nothing behind it. A "
        "vendor whose rating drops needs to read what customers actually said "
        "in order to do anything about it.",
    ),
    # --- Vendor app screens (ui/full vendor) --------------------------------
    (
        "GET",
        "/vendor/dashboard",
        "The app's two landing tabs (Order header, Overview) would need five "
        "endpoints per app-resume on a kitchen tablet's connection; this is "
        "those five queries in one response.",
    ),
    (
        "GET",
        "/vendor/performance",
        "The Performance & ratings screen: acceptance rate, on-time rate and "
        "weekly rejections exist nowhere else in the API.",
    ),
    (
        "GET",
        "/vendor/reviews/summary",
        "The Feedback header needs the star histogram; the paginated review "
        "list cannot produce it without fetching every page.",
    ),
    (
        "GET",
        "/vendor/reports/csv",
        "The Report screen's CSV download. Returns text/csv, not the JSON "
        "envelope — the response is a file.",
    ),
    (
        "GET",
        "/vendor/earnings",
        "The Earnings & payouts screen: available balance and recent per-order "
        "credits. The balance is derived from delivered orders minus payouts, "
        "so no other endpoint could substitute.",
    ),
    (
        "GET",
        "/vendor/payouts",
        "Payout History. Every withdrawal with its status and receipt "
        "reference.",
    ),
    (
        "POST",
        "/vendor/payouts",
        "The Withdraw Money button. Without it, earnings could be displayed "
        "but never leave the platform.",
    ),
    (
        "GET",
        "/vendor/promotions",
        "The Promotions card list with live redemption and spend stats.",
    ),
    (
        "POST",
        "/vendor/promotions",
        "The New Promotion form. promo_codes existed but nothing let a vendor "
        "create a restaurant-scoped offer.",
    ),
    (
        "GET",
        "/vendor/promotions/{id}",
        "Promotion Details: stats plus the 7-day redemptions chart.",
    ),
    (
        "PATCH",
        "/vendor/promotions/{id}",
        "Pause promotion / End promotion early. A live offer nobody can stop "
        "is a budget hole.",
    ),
    (
        "GET",
        "/vendor/hours",
        "The Business Hour screen had nowhere to read the week from.",
    ),
    (
        "PUT",
        "/vendor/hours",
        "Saving the Business Hour screen. Informational until a scheduler "
        "exists — documented as such.",
    ),
    (
        "GET",
        "/admin/payouts",
        "The transfer work queue. A payout recorded as PROCESSING needs a "
        "human to see it before money can actually move.",
    ),
    (
        "POST",
        "/admin/payouts/{id}/complete",
        "Records that the transfer was executed; the vendor's history shows "
        "COMPLETED from this.",
    ),
    (
        "POST",
        "/admin/payouts/{id}/fail",
        "A bounced transfer. Marking FAILED is itself the refund — the "
        "balance formula excludes failed rows.",
    ),
    # --- Riders & dispatch --------------------------------------------------
    # The spec defines a RIDER role, orders.rider_id, live GPS and rider
    # earnings, but no way for a rider to exist or to arrive on an order.
    # Nothing wrote rider_id, so ck_orders_rider_required made spec #42 —
    # POST /vendor/orders/{id}/handoff — unreachable on every real order.
    (
        "GET",
        "/admin/riders",
        "Dispatch chooses from a pool nobody could see. An operator "
        "overriding an assignment needs the list dispatch was choosing from, "
        "with shift state and current load.",
    ),
    (
        "POST",
        "/admin/riders",
        "There is no rider signup and there should not be one — /auth/otp/send "
        "accepts CUSTOMER and VENDOR only. Without this endpoint no RIDER row "
        "could be created through the API at all, so the dispatch pool was "
        "permanently empty and the handoff permanently 409.",
    ),
    (
        "PATCH",
        "/admin/riders/{id}",
        "is_online and is_verified are what dispatch filters on, and both "
        "defaulted false with no endpoint to flip them. A rider who cannot go "
        "on shift is a row, not a courier.",
    ),
    (
        "POST",
        "/admin/orders/{id}/assign-rider",
        "The control-centre override every dispatch system has: a bike breaks "
        "down, a rider no-shows, the automatic choice is wrong. Deliberately "
        "admin-only — a vendor picking their own rider is not how delivery "
        "works, and adding it to the vendor API later would break a shipped app.",
    ),
    (
        "POST",
        "/admin/orders/{id}/deliver",
        "The fallback when a rider cannot mark their own delivery — dead "
        "phone, uninstalled app, a dispute settled for the customer. Separate "
        "from the rider endpoint so the status history shows who was actually "
        "at the door.",
    ),
    # --- The rider app ------------------------------------------------------
    # §7 names a RIDER and every order carries rider_id, but the spec defines
    # no endpoint a rider can call. PICKED_UP -> DELIVERED was therefore the
    # one transition nothing in the system could perform, which stranded every
    # order a step short of done and made earnings, payouts and reviews —
    # all derived from DELIVERED — unreachable.
    (
        "GET",
        "/rider/orders",
        "A courier with no way to see what they are carrying. Two tabs, the "
        "same working set the vendor queue has, scoped to the assigned rider.",
    ),
    (
        "GET",
        "/rider/orders/{id}",
        "Where to collect, what to collect, where it goes — and the handoff "
        "code. This is decision D3 as originally designed: the code on the "
        "rider's screen is what makes the vendor typing it back proof of "
        "presence rather than a formality.",
    ),
    (
        "POST",
        "/rider/orders/{id}/deliver",
        "The missing transition. Nothing wrote DELIVERED, so no order ever "
        "completed, no vendor could be paid for one, and no customer could "
        "review one.",
    ),
    (
        "PATCH",
        "/rider/me/shift",
        "Dispatch only assigns to riders who are online, and is_online had no "
        "endpoint a rider could reach — a courier could not clock on for their "
        "own shift.",
    ),
]

PREFIX = "/api/v1"

# Routes the app owns that are not part of the spec's 47.
INFRA_PATHS = {
    "/health",
    "/health/ready",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}


def _normalise(path: str) -> str:
    """Collapse every path-param name to {id} so the comparison is structural."""
    import re

    return re.sub(r"\{[^}]+\}", "{id}", path)


def _leaf_routes():
    """Flatten the router tree.

    FastAPI 0.141 keeps included routers nested as `_IncludedRouter` objects
    rather than splicing their routes into `app.routes`, so a flat iteration
    finds nothing. Leaf routes carry their path WITHOUT the mount prefix; that
    the prefix is actually applied is verified behaviourally in
    test_app_contract.py, which calls /api/v1/... over ASGI.
    """

    def walk(routes):
        out = []
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                out.extend(walk(inner.routes))
            else:
                out.append(r)
        return out

    return walk(app.routes)


def _registered() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in _leaf_routes():
        path = getattr(route, "path", "")
        if path in INFRA_PATHS:
            continue
        norm = _normalise(path)
        methods = getattr(route, "methods", None)
        if methods is None:  # APIWebSocketRoute exposes no .methods
            found.add(("WS", norm))
        else:
            for m in methods:
                if m not in {"HEAD", "OPTIONS"}:
                    found.add((m, norm))
    return found


def test_all_47_spec_endpoints_are_registered():
    registered = _registered()
    missing = [(n, m, p) for n, m, p in SPEC_ENDPOINTS if (m, _normalise(p)) not in registered]
    assert not missing, "endpoints from spec §5 are not wired: " + ", ".join(
        f"#{n} {m} {p}" for n, m, p in missing
    )


def test_no_undocumented_endpoints():
    """Every registered route traces back either to a numbered spec row or to an
    explicitly justified EXTENDED entry. Nothing may appear by accident."""
    expected = {(m, _normalise(p)) for _, m, p in SPEC_ENDPOINTS}
    expected |= {(m, _normalise(p)) for m, p, _ in EXTENDED_ENDPOINTS}
    extra = _registered() - expected
    assert not extra, (
        "endpoints exist that are neither in the spec nor declared EXTENDED: "
        f"{sorted(extra)}"
    )


def test_extended_endpoints_are_registered_and_justified():
    registered = _registered()
    for method, path, reason in EXTENDED_ENDPOINTS:
        assert (method, _normalise(path)) in registered, f"{method} {path} is not wired"
        assert len(reason) > 40, f"{method} {path} needs a real justification, not a label"


def test_endpoint_count_matches_spec_statistics():
    """Spec §11 states 47 unique endpoints — that figure is correct."""
    assert len(SPEC_ENDPOINTS) == 47
    assert len(_registered()) == 47 + len(EXTENDED_ENDPOINTS)


def test_method_distribution_matches_the_endpoint_table():
    """Counted from the §5 table, which is the authoritative list.

    NOTE — spec §11's per-method breakdown does NOT match its own §5 table and
    is not asserted here. §11 claims GET 21 / POST 20 / PUT 2 / PATCH 3 /
    DELETE 1, which sums to 47 and therefore leaves no room for the two
    WebSocket endpoints it also counts in that total. Counting §5 directly
    gives GET 15 / POST 23 / PUT 2 / PATCH 3 / DELETE 2 / WS 2 = 47. The total
    is right; the breakdown is wrong.

    Two DELETEs exist (#8 biometrics/disable, #17 addresses/{id}), not one.
    """
    from collections import Counter

    counts = Counter(m for _, m, _ in SPEC_ENDPOINTS)
    assert counts["GET"] == 15
    assert counts["POST"] == 23
    assert counts["PUT"] == 2
    assert counts["PATCH"] == 3
    assert counts["DELETE"] == 2
    assert counts["WS"] == 2
    assert sum(counts.values()) == 47
