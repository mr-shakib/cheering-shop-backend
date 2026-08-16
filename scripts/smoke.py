#!/usr/bin/env python
"""End-to-end smoke test against a running CR Shop API.

    ./scripts/smoke.py                                  # local (default)
    ./scripts/smoke.py https://srv1128440.hstgr.cloud   # production

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
