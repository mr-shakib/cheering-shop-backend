"""The response/error envelope from spec §2, and the security primitives."""

import pytest


async def test_health_returns_success_envelope(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"


async def test_unimplemented_endpoint_returns_501_in_error_envelope(client):
    """A scaffolded route must return a documented 501, not a 404 that looks
    like a routing bug."""
    r = await client.get("/api/v1/home/feed")
    assert r.status_code == 501
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_IMPLEMENTED"


async def test_missing_auth_returns_our_envelope_not_fastapis(client):
    """FastAPI's default is `{"detail": "Not authenticated"}` — the spec §2
    envelope must win on every path."""
    r = await client.get("/api/v1/users/me/security")
    assert r.status_code == 401
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert "detail" not in body


async def test_validation_failure_uses_spec_error_shape(client):
    r = await client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "short"})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_FAILED"
    assert isinstance(err["details"], list) and err["details"]


async def test_role_guard_rejects_wrong_actor(client, customer_token):
    """A real CUSTOMER token must not reach a vendor endpoint (spec §7).

    DB-backed on purpose: with a fabricated user id the request would fail at
    identity resolution and never exercise the role guard at all.
    """
    r = await client.get(
        "/api/v1/vendor/orders", headers={"Authorization": f"Bearer {customer_token}"}
    )
    assert r.status_code == 403, "a customer reached a vendor endpoint"
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "FORBIDDEN"
    # Crucially NOT 501 — the guard rejected it before the handler ran.


async def test_authenticated_customer_reaches_the_handler(client, customer_token):
    """The mirror of the test above: a correct role gets through to the stub,
    proving the 403 came from the guard and not from a broken dependency."""
    r = await client.get("/api/v1/cart", headers={"Authorization": f"Bearer {customer_token}"})
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "NOT_IMPLEMENTED"


def test_money_conversion_is_exact_not_float():
    """The classic float bug: int(10.55 * 100) == 1054, not 1055."""
    from app.core.money import percentage_of, to_major, to_minor

    assert to_minor("10.55") == 1055
    assert to_minor(1059) == 105900  # the spec's worked example
    assert to_major(105900) == pytest.approx(1059)
    assert percentage_of(105900, 1500) == 15885  # 15% VAT, matches the DB test


def test_rider_pin_hash_is_scoped_to_its_order():
    """Decision D3: the same PIN on two orders must not produce equal digests."""
    from app.core.security import generate_rider_pin, hash_rider_pin, verify_rider_pin

    pin = generate_rider_pin()
    assert len(pin) == 4 and pin.isdigit()

    a = hash_rider_pin(pin, "order-a")
    b = hash_rider_pin(pin, "order-b")
    assert a != b, "identical PINs correlate across orders"
    assert verify_rider_pin(pin, "order-a", a)
    assert not verify_rider_pin(pin, "order-b", a)


def test_password_hashing_roundtrip():
    """argon2 direct — passlib+bcrypt is broken on this Python."""
    from app.core.security import hash_password, verify_password

    h = hash_password("SecurePassword1!")
    assert h.startswith("$argon2id$")
    assert verify_password("SecurePassword1!", h)
    assert not verify_password("wrong", h)


def test_token_type_confusion_is_rejected():
    """A refresh token must not be usable where an access token is expected."""
    from app.core.errors import UnauthorizedError
    from app.core.security import create_refresh_token, decode_token

    refresh = create_refresh_token("00000000-0000-0000-0000-000000000001")
    with pytest.raises(UnauthorizedError):
        decode_token(refresh, expected_type="access")


@pytest.mark.parametrize(
    ("environment", "exposed"),
    [("local", True), ("test", True), ("staging", False), ("production", False)],
)
def test_otp_debug_exposure_is_allowlisted_not_just_non_production(environment, exposed):
    """Guards the gate on echoing OTP codes in API responses.

    Deliberately an allowlist rather than `not is_production`: staging is
    internet-facing and routinely carries real phone numbers and email
    addresses, so leaking live OTP codes there is a real compromise.
    """
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT=environment,
        DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/db",
        REDIS_URL="redis://localhost:6379/0",
        JWT_SECRET_KEY="x" * 40,
        RIDER_PIN_PEPPER="y" * 40,
        OTP_PEPPER="z" * 40,
        TOTP_ENCRYPTION_KEY="w" * 40,
    )
    assert s.expose_debug_secrets is exposed
