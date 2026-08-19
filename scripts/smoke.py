#!/usr/bin/env python
"""End-to-end smoke test against a running CR Shop API.

    ./scripts/smoke.py                                  # local (default)
    ./scripts/smoke.py https://api.cheeringshop.online   # production

Complements `pytest`, which runs against the code on your machine. This drives a
REAL deployment over HTTP — so it also exercises the reverse proxy, TLS, the
container's environment, and the network path. A green pytest with a broken
Traefik route looks identical from your laptop; this catches that.

TWO MODES, chosen automatically:

* Local/test  — `/auth/otp/send` returns `debug_code`, so the full signup →
  login → 2FA → refresh journey can run.
* Deployed    — codes are (correctly) withheld, so OTP-dependent steps are
  skipped and the public surface plus security posture are checked instead.

Exit code 0 = everything passed.
"""

from __future__ import annotations

import sys
import uuid

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
API = f"{BASE}/api/v1"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
passed = failed = skipped = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global passed, failed
    if condition:
        passed += 1
        print(f"  {GREEN}✓{RESET} {label}")
    else:
        failed += 1
        print(f"  {RED}✗{RESET} {label}" + (f"\n      {DIM}{detail}{RESET}" if detail else ""))
    return condition


def skip(label: str, why: str) -> None:
    global skipped
    skipped += 1
    print(f"  {YELLOW}–{RESET} {label} {DIM}({why}){RESET}")


def section(name: str) -> None:
    print(f"\n{name}")


def main() -> int:
    print(f"Smoke test: {BASE}")
    client = httpx.Client(timeout=30.0, follow_redirects=True)

    # ---------------------------------------------------------------- health
    section("Health")
    try:
        r = client.get(f"{BASE}/health")
    except Exception as exc:
        print(f"  {RED}✗ cannot reach {BASE}: {exc}{RESET}")
        return 1

    check("/health returns 200", r.status_code == 200, r.text[:200])
    body = r.json()
    check("response uses the spec §2 envelope", body.get("success") is True)
    env = body.get("data", {}).get("environment", "?")
    print(f"    {DIM}environment: {env}{RESET}")

    r = client.get(f"{BASE}/health/ready")
    ready = r.json().get("data", {})
    check("database reachable", ready.get("database", {}).get("status") == "ok", str(ready))
    check("redis reachable", ready.get("redis", {}).get("status") == "ok", str(ready))

    deployed = env not in {"local", "test"}

    # ------------------------------------------------------------ error shape
    section("Error contract")
    r = client.get(f"{API}/restaurants")
    check("unimplemented route returns 501", r.status_code == 501, f"got {r.status_code}")
    check(
        "501 body uses the error envelope",
        r.json().get("error", {}).get("code") == "NOT_IMPLEMENTED",
        r.text[:200],
    )

    r = client.get(f"{API}/users/me/security")
    check("missing auth returns 401", r.status_code == 401)
    check(
        "401 is our envelope, not FastAPI's",
        "detail" not in r.json() and r.json().get("error", {}).get("code") == "UNAUTHORIZED",
        r.text[:200],
    )

    r = client.post(f"{API}/auth/login", json={"email": "a@b.com", "password": "short"})
    check("validation failure returns 400", r.status_code == 400)
    check(
        "validation errors are itemised",
        isinstance(r.json().get("error", {}).get("details"), list),
        r.text[:200],
    )

    # --------------------------------------------------------------- security
    section("Security posture")
    ident = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(f"{API}/auth/otp/send", json={"email": ident})
    otp_ok = r.status_code == 200
    check("POST /auth/otp/send accepted", otp_ok, r.text[:200])
    data = r.json().get("data", {}) if otp_ok else {}
    debug_code = data.get("debug_code")

    if deployed:
        check(
            "OTP code NOT leaked in response",
            debug_code is None,
            "debug_code present — ENVIRONMENT is not production!",
        )
    else:
        check("debug_code available for local testing", debug_code is not None)

    r = client.post(f"{API}/auth/otp/send", json={"email": ident})
    check("resend is rate limited (429)", r.status_code == 429, f"got {r.status_code}")
    check("429 carries Retry-After", "retry-after" in {k.lower() for k in r.headers})

    codes = [
        client.post(
            f"{API}/auth/login",
            json={"email": ident, "password": "WrongPassword1!"},
        ).status_code
        for _ in range(12)
    ]
    check("login brute-force is limited", 429 in codes, f"statuses: {codes}")

    r = client.get(f"{BASE}/docs")
    if r.status_code == 200:
        print(f"  {YELLOW}!{RESET} /docs is PUBLIC "
              f"{DIM}(fine while integrating; set ENABLE_DOCS=false before real users){RESET}")
    else:
        print(f"  {GREEN}✓{RESET} /docs hidden (HTTP {r.status_code})")

    # ------------------------------------------------------------ full journey
    section("Auth journey")
    if debug_code is None:
        skip("signup → login → 2FA → refresh", "OTP codes withheld in deployed environments")
        print(f"    {DIM}Run against a local server to exercise the full flow.{RESET}")
    else:
        r = client.post(f"{API}/auth/otp/verify", json={"email": ident, "code": debug_code})
        ok = check("OTP verify issues a session", r.status_code == 200, r.text[:200])
        if ok:
            tokens = r.json()["data"]["tokens"]
            access, refresh = tokens["access_token"], tokens["refresh_token"]
            auth = {"Authorization": f"Bearer {access}"}

            r = client.get(f"{API}/users/me/security", headers=auth)
            check("authenticated request succeeds", r.status_code == 200, r.text[:200])
            check("2FA reported disabled initially",
                  r.json()["data"]["is_2fa_enabled"] is False)

            r = client.post(f"{API}/auth/2fa/generate", headers=auth)
            check("TOTP secret generated", r.status_code == 200, r.text[:200])
            if r.status_code == 200:
                secret = r.json()["data"]["secret"]
                check("QR provisioning URI returned",
                      r.json()["data"]["qr_code_url"].startswith("otpauth://"))
                try:
                    import pyotp

                    code = pyotp.TOTP(secret).now()
                    r = client.post(f"{API}/auth/2fa/enable", json={"code": code}, headers=auth)
                    check("2FA enabled with a valid code", r.status_code == 200, r.text[:200])

                    r = client.post(f"{API}/auth/2fa/disable", json={"code": "000000"},
                                    headers=auth)
                    check("2FA disable rejects a wrong code", r.status_code == 400)

                    r = client.post(f"{API}/auth/2fa/disable",
                                    json={"code": pyotp.TOTP(secret).now()}, headers=auth)
                    check("2FA disabled with a valid code", r.status_code == 200, r.text[:200])
                except ImportError:
                    skip("TOTP enable/disable", "pyotp not installed")

            r = client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
            rotated = check("refresh returns a new pair", r.status_code == 200, r.text[:200])
            if rotated:
                new_refresh = r.json()["data"]["tokens"]["refresh_token"]
                check("refresh token actually rotated", new_refresh != refresh)
                r = client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
                check("reusing the old token is rejected", r.status_code == 401)
                r = client.post(f"{API}/auth/refresh", json={"refresh_token": new_refresh})
                check("reuse revokes the whole session family", r.status_code == 401)

    # ----------------------------------------------------------- vendor journey
    section("Vendor journey")
    if deployed:
        skip(
            "vendor signup → menu → store status",
            "would leave a real restaurant behind on a deployed server",
        )
    else:
        vendor_ident = f"smoke-vendor-{uuid.uuid4().hex[:10]}@example.com"
        r = client.post(f"{API}/auth/otp/send", json={"email": vendor_ident, "role": "VENDOR"})
        vendor_code = r.json().get("data", {}).get("debug_code") if r.status_code == 200 else None

        if not check("vendor OTP issued", vendor_code is not None, r.text[:200]):
            pass
        else:
            r = client.post(
                f"{API}/auth/register/vendor",
                json={
                    "email": vendor_ident,
                    "code": vendor_code,
                    "password": "VendorPass1!",
                    "full_name": "Smoke Vendor",
                    "restaurant": {
                        "name": f"Smoke Kitchen {uuid.uuid4().hex[:6]}",
                        "address_line": "House 12, Road 8, Dhanmondi, Dhaka",
                        "latitude": 23.7936,
                        "longitude": 90.4064,
                        "cuisine_types": ["Bengali"],
                    },
                },
            )
            registered = check("vendor registered", r.status_code == 201, r.text[:300])

            if registered:
                vauth = {"Authorization": f"Bearer {r.json()['data']['tokens']['access_token']}"}

                r = client.get(f"{API}/vendor/profile", headers=vauth)
                check("vendor reads own storefront", r.status_code == 200, r.text[:200])
                if r.status_code == 200:
                    profile = r.json()["data"]
                    # The approval gate: readable, but not sellable.
                    check("new restaurant is unapproved", profile["is_verified"] is False)
                    check("and not accepting orders", profile["is_accepting_orders"] is False)

                r = client.patch(
                    f"{API}/vendor/profile", json={"delivery_fee_base": 60}, headers=vauth
                )
                check(
                    "storefront is editable",
                    r.status_code == 200 and r.json()["data"]["delivery_fee_base"] == 60,
                    r.text[:200],
                )

                r = client.patch(
                    f"{API}/vendor/profile", json={"commission_rate": 0}, headers=vauth
                )
                check("platform-owned fields are rejected", r.status_code == 400, r.text[:200])

                r = client.post(
                    f"{API}/vendor/menu/categories", json={"name": "Biryani"}, headers=vauth
                )
                created = check("category created", r.status_code == 201, r.text[:200])
                category_id = r.json()["data"]["id"] if created else None

                if category_id:
                    r = client.post(
                        f"{API}/vendor/menu/items",
                        json={
                            "name": "Chicken Biryani",
                            "category_id": category_id,
                            "base_price": 180,
                            "variants": [
                                {"name": "Half", "price": 180, "is_default": True},
                                {"name": "Full", "price": 320},
                            ],
                            "add_ons": [{"name": "Extra raita", "price": 30}],
                        },
                        headers=vauth,
                    )
                    item_ok = check("item created with options", r.status_code == 201, r.text[:300])
                    if item_ok:
                        item = r.json()["data"]
                        check(
                            "variants keep their submitted order",
                            [v["name"] for v in item["variants"]] == ["Half", "Full"],
                            str([v["name"] for v in item["variants"]]),
                        )
                        r = client.patch(
                            f"{API}/vendor/menu/items/{item['id']}/status",
                            json={"is_available": False},
                            headers=vauth,
                        )
                        check("sold-out toggle works", r.status_code == 200, r.text[:200])

                    r = client.delete(
                        f"{API}/vendor/menu/categories/{category_id}", headers=vauth
                    )
                    check(
                        "deleting a populated category is refused",
                        r.status_code == 409,
                        f"got {r.status_code}",
                    )

                r = client.get(f"{API}/vendor/menu", headers=vauth)
                check("full menu tree returned", r.status_code == 200, r.text[:200])

                r = client.patch(
                    f"{API}/vendor/store/status", json={"status": "OPEN"}, headers=vauth
                )
                check(
                    "opening an unapproved store is honest",
                    r.status_code == 200 and r.json()["data"]["is_accepting_orders"] is False,
                    r.text[:300],
                )

                r = client.get(f"{API}/vendor/orders?status=ACTIVE", headers=vauth)
                check("order queue reachable", r.status_code == 200, r.text[:200])

                r = client.get(f"{API}/vendor/analytics", headers=vauth)
                check(
                    "analytics returns an empty window",
                    r.status_code == 200 and r.json()["data"]["totals"]["orders"] == 0,
                    r.text[:200],
                )

    # ------------------------------------------------------------------ done
    print()
    total = passed + failed
    colour = GREEN if failed == 0 else RED
    print(f"{colour}{passed}/{total} passed{RESET}"
          + (f", {failed} failed" if failed else "")
          + (f", {skipped} skipped" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
