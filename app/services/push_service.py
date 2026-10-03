"""Push notifications through Firebase Cloud Messaging (HTTP v1).

Disabled unless `FCM_SERVICE_ACCOUNT_JSON` is set, the same "no key, no
feature" rule email follows. Callers treat push as best effort: the in-app
inbox is the record, push is the nudge.

Authentication is the service-account OAuth flow done by hand — a JWT signed
with the account's private key, exchanged for a one-hour access token — so no
Google SDK is needed. The token is cached in-process until shortly before it
expires.

A token FCM reports as UNREGISTERED (the app was uninstalled, or the token
rotated) is deactivated so it is not tried again.
"""

import asyncio
import base64
import binascii
import json
import time
from dataclasses import dataclass

import httpx
import jwt
import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import UserDevice

log = structlog.get_logger()

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_CONCURRENCY = 20

_cached: dict = {"token": None, "expires_at": 0.0}


@dataclass(frozen=True)
class PushResult:
    sent: int
    failed: int
    deactivated: int


def enabled() -> bool:
    return bool(settings.FCM_SERVICE_ACCOUNT_JSON.strip())


def _account() -> dict:
    """The key file's JSON, inline or base64-encoded. Base64 is there for env
    editors that mangle the quotes and `\\n`s in a pasted private key."""
    raw = settings.FCM_SERVICE_ACCOUNT_JSON.strip()
    if not raw.startswith("{"):
        try:
            raw = base64.b64decode(raw, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("FCM_SERVICE_ACCOUNT_JSON is neither JSON nor base64") from exc
    return json.loads(raw)


def check_push_config() -> dict:
    """Readiness detail, mirroring `check_storage_config`. Reported but not
    gating: orders work without push, they just do not buzz a phone. Parses the
    key, so a value mangled on its way into the container shows here rather
    than as a silent `push_auth_failed` on the first order."""
    if not enabled():
        if settings.ENVIRONMENT in {"local", "test"}:
            return {"status": "disabled", "detail": "FCM_SERVICE_ACCOUNT_JSON unset (fine locally)"}
        return {"status": "error", "detail": "FCM_SERVICE_ACCOUNT_JSON unset"}
    try:
        account = _account()
        missing = [k for k in ("project_id", "client_email", "private_key") if not account.get(k)]
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        return {"status": "error", "detail": f"FCM_SERVICE_ACCOUNT_JSON unreadable: {exc}"}
    if missing:
        return {"status": "error", "detail": f"key is missing {', '.join(missing)}"}
    return {"status": "ok", "provider": "fcm", "project": account["project_id"]}


async def _access_token(client: httpx.AsyncClient) -> str:
    if _cached["token"] and _cached["expires_at"] - 60 > time.time():
        return _cached["token"]
    account = _account()
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": account["client_email"],
            "scope": _SCOPE,
            "aud": _TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        account["private_key"],
        algorithm="RS256",
    )
    response = await client.post(
        _TOKEN_URL,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
    )
    response.raise_for_status()
    body = response.json()
    _cached.update(token=body["access_token"], expires_at=now + int(body.get("expires_in", 3600)))
    return body["access_token"]


async def send(
    db: AsyncSession, tokens: list[str], title: str, body: str, data: dict[str, str] | None = None
) -> PushResult:
    """Send one notification to many devices. Never raises: a push failure is
    logged and counted, not propagated into the caller's transaction."""
    if not enabled() or not tokens:
        return PushResult(sent=0, failed=0, deactivated=0)

    url = f"https://fcm.googleapis.com/v1/projects/{_account()['project_id']}/messages:send"
    dead: list[str] = []
    sent = failed = 0
    gate = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient(timeout=settings.FCM_TIMEOUT_SECONDS) as client:
        try:
            access = await _access_token(client)
        except Exception as exc:
            log.error("push_auth_failed", error=str(exc))
            return PushResult(sent=0, failed=len(tokens), deactivated=0)

        async def one(token: str) -> None:
            nonlocal sent, failed
            message = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": data or {},
                    # Sound on both platforms. iOS is silent without it, and a
                    # vendor phone that lights up without a sound in the lunch
                    # rush is a missed order.
                    "android": {"priority": "HIGH", "notification": {"sound": "default"}},
                    "apns": {"payload": {"aps": {"sound": "default"}}},
                }
            }
            async with gate:
                try:
                    r = await client.post(
                        url, json=message, headers={"Authorization": f"Bearer {access}"}
                    )
                except httpx.HTTPError as exc:
                    failed += 1
                    log.warning("push_send_error", error=str(exc))
                    return
            if r.status_code == 200:
                sent += 1
                return
            failed += 1
            # UNREGISTERED: uninstalled or rotated. "Not a valid … token": it
            # never was one. Either way, trying it again cannot succeed.
            if (
                r.status_code == 404
                or "UNREGISTERED" in r.text
                or "not a valid FCM registration token" in r.text
            ):
                dead.append(token)

        await asyncio.gather(*(one(t) for t in tokens))

    if dead:
        await db.execute(
            update(UserDevice).where(UserDevice.fcm_token.in_(dead)).values(is_active=False)
        )
    log.info("push_sent", sent=sent, failed=failed, deactivated=len(dead))
    return PushResult(sent=sent, failed=failed, deactivated=len(dead))
