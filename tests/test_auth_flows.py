"""Auth module integration tests — real Postgres, real Redis, no mocks.

Mocking the database here would defeat the purpose: several of these behaviours
(citext email matching, the 2FA CHECK constraint, OTP single-use) are enforced
by the database, and a mock would happily let a broken implementation pass.
"""

import uuid

import pyotp
import pytest

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


def _identifier() -> str:
    return f"auth-{uuid.uuid4().hex[:12]}@example.com"


async def _signup(client) -> tuple[str, dict]:
    """Complete the OTP signup flow, returning (identifier, token payload)."""
    ident = _identifier()
    r = await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})
    assert r.status_code == 200, r.text
    code = r.json()["data"]["debug_code"]

    r = await client.post(f"{V1}/auth/otp/verify", json={"identifier": ident, "code": code})
    assert r.status_code == 200, r.text
    return ident, r.json()["data"]


# ---------------------------------------------------------------------------
# OTP signup
# ---------------------------------------------------------------------------
async def test_otp_signup_issues_a_working_session(client, cleanup_users):
    ident, data = await _signup(client)
    cleanup_users(ident)

    assert data["tokens"]["token_type"] == "Bearer"
    assert data["user"]["is_email_verified"] is True

    token = data["tokens"]["access_token"]
    r = await client.get(f"{V1}/users/me/security", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["data"]["is_2fa_enabled"] is False


async def test_otp_is_single_use(client, cleanup_users):
    ident = _identifier()
    cleanup_users(ident)
    r = await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})
    code = r.json()["data"]["debug_code"]

    assert (
        await client.post(f"{V1}/auth/otp/verify", json={"identifier": ident, "code": code})
    ).status_code == 200

    # Replaying an observed code must fail.
    replay = await client.post(f"{V1}/auth/otp/verify", json={"identifier": ident, "code": code})
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "INVALID_OTP"


async def test_otp_resend_is_rate_limited(client, cleanup_users):
    """Spec §4 requires 429. Guards against SMS-pumping and victim spam."""
    ident = _identifier()
    cleanup_users(ident)
    assert (await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})).status_code == 200

    second = await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in second.headers


async def test_wrong_otp_is_rejected(client, cleanup_users, reset_limits):
    ident = _identifier()
    cleanup_users(ident)
    await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})
    r = await client.post(f"{V1}/auth/otp/verify", json={"identifier": ident, "code": "0000"})
    assert r.status_code == 400


async def test_otp_is_four_digits(client, cleanup_users, reset_limits):
    ident = _identifier()
    cleanup_users(ident)
    r = await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})
    code = r.json()["data"]["debug_code"]
    assert len(code) == 4 and code.isdigit(), f"expected a 4-digit code, got {code!r}"


async def test_otp_guessing_is_capped_per_identifier(client, cleanup_users, reset_limits):
    """The budget that actually protects a 4-digit code.

    10,000 candidates means code length is not the defence — the per-identifier
    hourly ceiling is. Without it an attacker requests a fresh code each minute
    and grinds the space indefinitely.
    """
    from app.core.config import settings

    ident = _identifier()
    cleanup_users(ident)
    await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})

    statuses = []
    for _ in range(settings.OTP_VERIFY_MAX_PER_HOUR + 3):
        r = await client.post(f"{V1}/auth/otp/verify", json={"identifier": ident, "code": "0000"})
        statuses.append(r.status_code)

    assert 429 in statuses, f"guessing was never rate limited: {statuses}"


# ---------------------------------------------------------------------------
# Password login
# ---------------------------------------------------------------------------
async def test_login_rejects_unknown_and_wrong_password_identically(client, cleanup_users):
    """Both failures must be indistinguishable, or login becomes an account
    enumeration oracle."""
    ident, _ = await _signup(client)
    cleanup_users(ident)
    await _set_password(ident, "CorrectHorse1!")

    unknown = await client.post(
        f"{V1}/auth/login", json={"identifier": _identifier(), "password": "CorrectHorse1!"}
    )
    wrong = await client.post(
        f"{V1}/auth/login", json={"identifier": ident, "password": "WrongPassword1!"}
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"] == wrong.json()["error"], (
        "responses differ, leaking whether the account exists"
    )


async def _set_password(identifier: str, password: str) -> None:
    from app.core.database import SessionLocal
    from app.services import auth_service

    async with SessionLocal() as session:
        user = await auth_service.find_by_identifier(session, identifier)
        await auth_service.set_password(session, user, password)
        await session.commit()


async def test_email_matching_is_case_insensitive(client, cleanup_users):
    """`users.email` is citext — User@x.com and user@x.com are the same account."""
    ident, _ = await _signup(client)
    cleanup_users(ident)
    await _set_password(ident, "CorrectHorse1!")

    r = await client.post(
        f"{V1}/auth/login", json={"identifier": ident.upper(), "password": "CorrectHorse1!"}
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# TOTP 2FA
# ---------------------------------------------------------------------------
async def test_full_2fa_enrolment_and_login_interception(client, cleanup_users):
    ident, data = await _signup(client)
    cleanup_users(ident)
    await _set_password(ident, "CorrectHorse1!")
    auth = {"Authorization": f"Bearer {data['tokens']['access_token']}"}

    # Enrol
    gen = await client.post(f"{V1}/auth/2fa/generate", headers=auth)
    assert gen.status_code == 200
    secret = gen.json()["data"]["secret"]
    assert gen.json()["data"]["qr_code_url"].startswith("otpauth://")

    # Not enabled until proven
    state = await client.get(f"{V1}/users/me/security", headers=auth)
    assert state.json()["data"]["is_2fa_enabled"] is False

    totp = pyotp.TOTP(secret)
    enable = await client.post(f"{V1}/auth/2fa/enable", json={"code": totp.now()}, headers=auth)
    assert enable.status_code == 200, enable.text

    # Login is now intercepted — no access token issued
    login = await client.post(
        f"{V1}/auth/login", json={"identifier": ident, "password": "CorrectHorse1!"}
    )
    assert login.status_code == 200
    body = login.json()["data"]
    assert body["requires_2fa"] is True
    assert "access_token" not in body
    temp_token = body["temp_token"]

    # A temp token must not work as an access token
    misuse = await client.get(
        f"{V1}/users/me/security", headers={"Authorization": f"Bearer {temp_token}"}
    )
    assert misuse.status_code == 401

    # Wrong code fails
    bad = await client.post(
        f"{V1}/auth/login/2fa", json={"temp_token": temp_token, "code": "000000"}
    )
    assert bad.status_code == 401

    # Correct code completes login
    good = await client.post(
        f"{V1}/auth/login/2fa", json={"temp_token": temp_token, "code": totp.now()}
    )
    assert good.status_code == 200, good.text
    assert "access_token" in good.json()["data"]["tokens"]


async def test_disabling_2fa_requires_a_current_code(client, cleanup_users):
    """A stolen access token alone must not be able to switch off the second
    factor — otherwise 2FA protects nothing."""
    ident, data = await _signup(client)
    cleanup_users(ident)
    auth = {"Authorization": f"Bearer {data['tokens']['access_token']}"}

    secret = (await client.post(f"{V1}/auth/2fa/generate", headers=auth)).json()["data"]["secret"]
    totp = pyotp.TOTP(secret)
    await client.post(f"{V1}/auth/2fa/enable", json={"code": totp.now()}, headers=auth)

    bad = await client.post(f"{V1}/auth/2fa/disable", json={"code": "000000"}, headers=auth)
    assert bad.status_code == 400

    good = await client.post(f"{V1}/auth/2fa/disable", json={"code": totp.now()}, headers=auth)
    assert good.status_code == 200
    state = await client.get(f"{V1}/users/me/security", headers=auth)
    assert state.json()["data"]["is_2fa_enabled"] is False


async def test_totp_secret_is_encrypted_at_rest(client, cleanup_users):
    """The stored value must not be the base32 secret in plaintext."""
    ident, data = await _signup(client)
    cleanup_users(ident)
    auth = {"Authorization": f"Bearer {data['tokens']['access_token']}"}
    secret = (await client.post(f"{V1}/auth/2fa/generate", headers=auth)).json()["data"]["secret"]

    from app.core.database import SessionLocal
    from app.services import auth_service

    async with SessionLocal() as session:
        user = await auth_service.find_by_identifier(session, ident)
        stored = user.totp_pending_secret

    assert stored is not None
    assert secret not in stored, "TOTP secret is stored in plaintext"

    from app.core.crypto import decrypt_secret

    assert decrypt_secret(stored) == secret


# ---------------------------------------------------------------------------
# Refresh rotation  [EXTENDED]
# ---------------------------------------------------------------------------
async def test_refresh_rotates_and_old_token_is_dead(client, cleanup_users):
    ident, data = await _signup(client)
    cleanup_users(ident)
    original = data["tokens"]["refresh_token"]

    first = await client.post(f"{V1}/auth/refresh", json={"refresh_token": original})
    assert first.status_code == 200, first.text
    rotated = first.json()["data"]["tokens"]["refresh_token"]
    assert rotated != original, "refresh token was not rotated"

    # Reusing the original is treated as theft: the whole family is revoked.
    reuse = await client.post(f"{V1}/auth/refresh", json={"refresh_token": original})
    assert reuse.status_code == 401

    dead = await client.post(f"{V1}/auth/refresh", json={"refresh_token": rotated})
    assert dead.status_code == 401, "reuse detection did not revoke the session family"


async def test_access_token_cannot_be_used_as_refresh(client, cleanup_users):
    ident, data = await _signup(client)
    cleanup_users(ident)
    r = await client.post(
        f"{V1}/auth/refresh", json={"refresh_token": data["tokens"]["access_token"]}
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
async def test_password_reset_revokes_existing_sessions(client, cleanup_users):
    """An attacker already holding a session must be evicted by the reset."""
    ident, data = await _signup(client)
    cleanup_users(ident)
    await _set_password(ident, "OldPassword1!")
    stolen_refresh = data["tokens"]["refresh_token"]

    forgot = await client.post(f"{V1}/auth/password/forgot", json={"identifier": ident})
    assert forgot.status_code == 200
    code = forgot.json()["data"]["debug_code"]

    reset = await client.post(
        f"{V1}/auth/password/reset",
        json={"identifier": ident, "code": code, "new_password": "BrandNewPass1!"},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["data"]["sessions_revoked"] >= 1

    assert (
        await client.post(f"{V1}/auth/refresh", json={"refresh_token": stolen_refresh})
    ).status_code == 401

    assert (
        await client.post(
            f"{V1}/auth/login", json={"identifier": ident, "password": "BrandNewPass1!"}
        )
    ).status_code == 200


async def test_forgot_password_does_not_reveal_account_existence(client):
    """Identical response for a real and a non-existent identifier."""
    unknown = await client.post(f"{V1}/auth/password/forgot", json={"identifier": _identifier()})
    assert unknown.status_code == 200
    assert "debug_code" not in unknown.json()["data"]
    assert unknown.json()["data"]["message"] == "If an account exists, a reset code has been sent"


# ---------------------------------------------------------------------------
# Biometrics
# ---------------------------------------------------------------------------
async def test_biometric_enrolment_roundtrip(client, cleanup_users):
    ident, data = await _signup(client)
    cleanup_users(ident)
    auth = {"Authorization": f"Bearer {data['tokens']['access_token']}"}

    r = await client.post(
        f"{V1}/auth/biometrics/enable",
        json={"device_id": "pixel-9-abc", "device_name": "Pixel 9", "public_key": "BASE64KEY=="},
        headers=auth,
    )
    assert r.status_code == 200, r.text

    state = (await client.get(f"{V1}/users/me/security", headers=auth)).json()["data"]
    assert state["is_biometrics_enabled"] is True
    assert state["biometric_device_count"] == 1

    off = await client.request("DELETE", f"{V1}/auth/biometrics/disable", headers=auth)
    assert off.status_code == 200
    state = (await client.get(f"{V1}/users/me/security", headers=auth)).json()["data"]
    assert state["is_biometrics_enabled"] is False


# ---------------------------------------------------------------------------
# Brute-force protection
# ---------------------------------------------------------------------------
async def test_login_is_brute_force_limited_per_identifier(client, cleanup_users, reset_limits):
    """Without this, /auth/login is an open password-guessing oracle."""
    ident, _ = await _signup(client)
    cleanup_users(ident)
    await _set_password(ident, "CorrectHorse1!")

    from app.core.config import settings

    statuses = []
    for _ in range(settings.LOGIN_MAX_ATTEMPTS + 2):
        r = await client.post(
            f"{V1}/auth/login", json={"identifier": ident, "password": "WrongPassword1!"}
        )
        statuses.append(r.status_code)

    assert 429 in statuses, f"login never rate limited: {statuses}"
    blocked = await client.post(
        f"{V1}/auth/login", json={"identifier": ident, "password": "CorrectHorse1!"}
    )
    assert blocked.status_code == 429, "correct password bypassed the lockout"
    assert "Retry-After" in blocked.headers


async def test_successful_login_clears_the_identifier_counter(client, cleanup_users, reset_limits):
    """A few typos must not lock a legitimate user out for 15 minutes."""
    ident, _ = await _signup(client)
    cleanup_users(ident)
    await _set_password(ident, "CorrectHorse1!")

    for _ in range(3):
        await client.post(
            f"{V1}/auth/login", json={"identifier": ident, "password": "WrongPassword1!"}
        )

    ok_login = await client.post(
        f"{V1}/auth/login", json={"identifier": ident, "password": "CorrectHorse1!"}
    )
    assert ok_login.status_code == 200

    from app.core.rate_limit import login_identifier_key
    from app.core.redis import get_redis

    assert await get_redis().get(login_identifier_key(ident)) is None


async def test_ip_counter_survives_a_successful_login(client, cleanup_users, reset_limits):
    """Resetting the IP budget on success would let an attacker refresh their
    allowance by logging into an account they control between guesses."""
    ident, _ = await _signup(client)
    cleanup_users(ident)
    await _set_password(ident, "CorrectHorse1!")

    await client.post(f"{V1}/auth/login", json={"identifier": ident, "password": "nope-nope-1!"})
    await client.post(f"{V1}/auth/login", json={"identifier": ident, "password": "CorrectHorse1!"})

    from app.core.client import client_ip  # noqa: F401  (documents the source of the key)
    from app.core.rate_limit import login_ip_key
    from app.core.redis import get_redis

    keys = [k async for k in get_redis().scan_iter("rl:login:ip:*")]
    assert keys, "no per-IP counter was recorded"
    assert int(await get_redis().get(keys[0])) >= 2, "IP counter was wrongly cleared on success"
    assert login_ip_key  # referenced for clarity


# ---------------------------------------------------------------------------
# Signup completeness — the gaps that blocked a real phone user
# ---------------------------------------------------------------------------
async def test_signup_can_set_a_password_in_one_round_trip(client, cleanup_users, reset_limits):
    """Before this, a new account could never obtain a password: set_password
    was only reachable via /auth/password/reset, which itself needs an OTP."""
    ident = _identifier()
    cleanup_users(ident)
    r = await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})
    code = r.json()["data"]["debug_code"]

    r = await client.post(
        f"{V1}/auth/otp/verify",
        json={"identifier": ident, "code": code, "password": "FirstPassword1!",
              "full_name": "Test Person"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["user"]["full_name"] == "Test Person"

    # The password works immediately — no reset flow required.
    login = await client.post(
        f"{V1}/auth/login", json={"identifier": ident, "password": "FirstPassword1!"}
    )
    assert login.status_code == 200, login.text


async def test_get_me_returns_the_token_owner(client, cleanup_users):
    ident, data = await _signup(client)
    cleanup_users(ident)
    auth = {"Authorization": f"Bearer {data['tokens']['access_token']}"}

    r = await client.get(f"{V1}/users/me", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["email"] == ident
    assert r.json()["data"]["role"] == "CUSTOMER"


async def test_profile_update_replaces_fields(client, cleanup_users):
    ident, data = await _signup(client)
    cleanup_users(ident)
    auth = {"Authorization": f"Bearer {data['tokens']['access_token']}"}

    r = await client.put(
        f"{V1}/users/me/profile",
        json={"full_name": "Ada Lovelace", "avatar_url": "https://cdn/x.jpg"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["full_name"] == "Ada Lovelace"

    # PUT semantics: an omitted field is cleared, not preserved.
    r = await client.put(f"{V1}/users/me/profile", json={"full_name": "Ada"}, headers=auth)
    assert r.json()["data"]["avatar_url"] is None


async def test_change_password_requires_the_current_one(client, cleanup_users, reset_limits):
    """A stolen access token alone must not let an attacker lock the owner out."""
    ident, data = await _signup(client)
    cleanup_users(ident)
    auth = {"Authorization": f"Bearer {data['tokens']['access_token']}"}

    # No password yet (OTP-only signup) — first set is allowed without a current.
    r = await client.post(
        f"{V1}/users/me/password", json={"new_password": "InitialPass1!"}, headers=auth
    )
    assert r.status_code == 200, r.text

    # Now one exists, so changing it demands the current value.
    r = await client.post(
        f"{V1}/users/me/password", json={"new_password": "SecondPass1!"}, headers=auth
    )
    assert r.status_code == 400

    r = await client.post(
        f"{V1}/users/me/password",
        json={"current_password": "WrongOne1!", "new_password": "SecondPass1!"},
        headers=auth,
    )
    assert r.status_code == 401

    r = await client.post(
        f"{V1}/users/me/password",
        json={"current_password": "InitialPass1!", "new_password": "SecondPass1!"},
        headers=auth,
    )
    assert r.status_code == 200, r.text


async def test_logout_actually_revokes_the_session(client, cleanup_users):
    """Without this, 'log out' only cleared local storage — the refresh token
    stayed valid for 30 days on a stolen device."""
    ident, data = await _signup(client)
    cleanup_users(ident)
    access = data["tokens"]["access_token"]
    refresh = data["tokens"]["refresh_token"]

    r = await client.post(
        f"{V1}/auth/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["sessions_revoked"] == 1

    # The refresh token is dead.
    r = await client.post(f"{V1}/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401

    # Idempotent — logging out twice is not an error.
    r = await client.post(
        f"{V1}/auth/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200


async def test_logout_cannot_end_another_users_session(client, cleanup_users):
    """revoke_one is scoped by user_id, so a token you happen to hold is not
    enough to sign somebody else out."""
    ident_a, data_a = await _signup(client)
    cleanup_users(ident_a)
    ident_b, data_b = await _signup(client)
    cleanup_users(ident_b)

    r = await client.post(
        f"{V1}/auth/logout",
        json={"refresh_token": data_b["tokens"]["refresh_token"]},
        headers={"Authorization": f"Bearer {data_a['tokens']['access_token']}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["sessions_revoked"] == 0, "user A revoked user B's session"

    # B's session still works.
    r = await client.post(
        f"{V1}/auth/refresh", json={"refresh_token": data_b["tokens"]["refresh_token"]}
    )
    assert r.status_code == 200, "user B was wrongly signed out"


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------
async def test_otp_send_survives_a_provider_outage(client, cleanup_users, reset_limits, monkeypatch):
    """A Resend outage must not take signup down with it.

    The code is already stored when delivery is attempted, so a failure is
    recoverable by resending. Propagating the error would also make
    /auth/password/forgot distinguish real accounts from fake ones — the exact
    enumeration leak it is written to avoid.
    """
    from app.services import email_service, otp_service

    async def boom(*_a, **_kw):
        raise email_service.EmailDeliveryError("503: provider down")

    monkeypatch.setattr(otp_service.email_service, "send_email", boom)

    ident = _identifier()
    cleanup_users(ident)
    r = await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})
    assert r.status_code == 200, "a mail outage broke signup"

    # And the code still works, because storage succeeded.
    code = r.json()["data"]["debug_code"]
    r = await client.post(f"{V1}/auth/otp/verify", json={"identifier": ident, "code": code})
    assert r.status_code == 200, r.text


async def test_email_is_dispatched_for_email_identifiers(client, cleanup_users, reset_limits, monkeypatch):
    """The generated code must be the one that actually gets mailed."""
    from app.services import otp_service

    sent: dict = {}

    async def capture(to, subject, html, text):
        sent.update(to=to, subject=subject, html=html, text=text)
        return "msg_test"

    monkeypatch.setattr(otp_service.email_service, "send_email", capture)

    ident = _identifier()
    cleanup_users(ident)
    r = await client.post(f"{V1}/auth/otp/send", json={"identifier": ident})
    code = r.json()["data"]["debug_code"]

    assert sent["to"] == ident
    assert code in sent["html"] and code in sent["text"], "code missing from the body"
    assert code not in sent["subject"], (
        "the code is in the subject line — it would appear in lock-screen "
        "notification previews, readable without unlocking the phone"
    )


async def test_password_reset_uses_a_different_template(client, cleanup_users, reset_limits, monkeypatch):
    """A reset email must not tell the user they are creating an account."""
    from app.services import otp_service

    sent: dict = {}

    async def capture(to, subject, html, text):
        sent.update(subject=subject, text=text)
        return "msg_test"

    ident, _ = await _signup(client)
    cleanup_users(ident)
    monkeypatch.setattr(otp_service.email_service, "send_email", capture)

    r = await client.post(f"{V1}/auth/password/forgot", json={"identifier": ident})
    assert r.status_code == 200
    assert "reset" in sent["subject"].lower()
    assert "password has not changed" in sent["text"].lower()
