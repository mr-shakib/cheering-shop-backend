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
