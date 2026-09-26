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
    return json.loads(settings.FCM_SERVICE_ACCOUNT_JSON)


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
            if r.status_code == 404 or "UNREGISTERED" in r.text:
                dead.append(token)

        await asyncio.gather(*(one(t) for t in tokens))

    if dead:
        await db.execute(
            update(UserDevice).where(UserDevice.fcm_token.in_(dead)).values(is_active=False)
        )
    log.info("push_sent", sent=sent, failed=failed, deactivated=len(dead))
    return PushResult(sent=sent, failed=failed, deactivated=len(dead))
