"""Sign in with Google — the OpenID Connect authorization-code flow.

The browser is redirected to Google and returns to this backend, so the whole
exchange happens server-side and the client secret never leaves the server.
The mobile app's only involvement is opening a URL and catching the deep link
at the end.

Three things carry the security of this flow, and none of them are optional:

* **PKCE.** The authorization code travels back through a URL the operating
  system hands to whichever app claims the scheme. Custom schemes are not
  exclusive — a malicious app can register the same one and race for the
  redirect. PKCE makes an intercepted code useless without the verifier, which
  never leaves this server.
* **Single-use `state`.** Binds the callback to an authorization this server
  actually started, which is what stops an attacker feeding their own code to
  a victim's session (CSRF login). Consumed with GETDEL so a replayed callback
  finds nothing.
* **An allowlisted redirect target.** The callback ends by handing a refresh
  token to a URL. If that URL came from the request unchecked, anyone could
  send themselves the victim's session — the classic open-redirect-to-token-
  theft. `settings.GOOGLE_POST_AUTH_REDIRECTS` is the allowlist; membership is
  exact-match, not prefix, because a prefix check on a custom scheme is
  trivially defeated.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
import structlog
from jwt import PyJWKSet

from app.core.config import settings
from app.core.errors import AppError, ErrorCode, UnauthorizedError, ValidationError
from app.core.redis import get_redis

log = structlog.get_logger()

# Google's OIDC endpoints. Hardcoded rather than read from the discovery
# document at /.well-known/openid-configuration: those URLs have been stable
# for a decade, and fetching them would add a network round trip to every
# sign-in for a value that never changes. The JWKS *contents* do rotate, which
# is why only that one is fetched (and cached) below.
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"

# Google still issues the bare-host form to some clients, so both are accepted.
ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})

# openid gets us the ID token, email and profile fill in the account. Nothing
# else is requested: any scope beyond these three is "sensitive" or
# "restricted" to Google and drags the project into a verification review.
SCOPES = "openid email profile"

_STATE_PREFIX = "oauth:google:state:"

# JWKS cache. Google rotates signing keys roughly daily and publishes the next
# one well before using it, so an hour is comfortably fresh; an unknown `kid`
# forces a refetch regardless (see _signing_key).
_JWKS_TTL_SECONDS = 3600
_jwks_cache: dict[str, Any] = {"fetched_at": 0.0, "keys": None}


class GoogleAuthUnavailable(AppError):
    """The deployment has no Google credentials configured."""

    status_code = 501

    def __init__(self) -> None:
        super().__init__(
            "Google sign-in is not configured on this server",
            code=ErrorCode.NOT_IMPLEMENTED,
        )


@dataclass(slots=True)
class GoogleProfile:
    """The verified claims we act on. Everything else in the token is ignored."""

    subject: str
    email: str
    email_verified: bool
    full_name: str | None
    avatar_url: str | None


@dataclass(slots=True)
class PendingAuthorization:
    """What /authorize hands the caller."""

    authorization_url: str
    state: str


# ---------------------------------------------------------------------------
# Redirect allowlist
# ---------------------------------------------------------------------------
def resolve_redirect(requested: str | None) -> str:
    """Pick the post-auth target, refusing anything not explicitly allowed.

    Exact match against the configured list. Deliberately NOT a prefix or
    hostname check: `crshop://auth/callback` and `crshop://auth/callback.evil`
    share a prefix, and a scheme has no hostname to compare, so anything
    looser than equality is not a check at all.
    """
    allowed = settings.GOOGLE_POST_AUTH_REDIRECTS
    if not allowed:
        raise GoogleAuthUnavailable()
    if requested is None:
        return allowed[0]
    if requested not in allowed:
        # The value is echoed back to nobody and logged, not returned: telling a
        # caller which targets exist is free reconnaissance.
        log.warning("google_redirect_rejected", requested=requested)
        raise ValidationError("redirect is not an allowed target for this application")
    return requested


# ---------------------------------------------------------------------------
# Step 1 — start the authorization
# ---------------------------------------------------------------------------
def _pkce_pair() -> tuple[str, str]:
    """(verifier, challenge) for PKCE S256, per RFC 7636."""
    verifier = secrets.token_urlsafe(64)  # ~86 chars, inside the 43–128 range
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


async def begin_authorization(*, redirect_target: str | None) -> PendingAuthorization:
    if not settings.google_auth_enabled:
        raise GoogleAuthUnavailable()

    target = resolve_redirect(redirect_target)
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)

    # The verifier is held here and never sent to the client. That is the whole
    # point of PKCE in a flow whose redirect can be intercepted.
    await get_redis().set(
        f"{_STATE_PREFIX}{state}",
        json.dumps({"verifier": verifier, "redirect": target}),
        ex=settings.GOOGLE_STATE_TTL_SECONDS,
    )

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Always show the chooser. Without it, a phone with one Google account
        # signs in instantly and silently, so a user who wanted a different
        # account has no way to reach one and no signal that a choice existed.
        "prompt": "select_account",
    }
    return PendingAuthorization(
        authorization_url=f"{AUTHORIZE_URL}?{urlencode(params)}",
        state=state,
    )


async def consume_state(state: str) -> dict[str, str]:
    """Redeem a pending authorization exactly once.

    GETDEL is atomic, so two callbacks racing on the same state produce one
    winner and one 401 rather than two sessions.
    """
    raw = await get_redis().getdel(f"{_STATE_PREFIX}{state}")
    if raw is None:
        raise UnauthorizedError("This sign-in link has expired or was already used")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Step 2 — exchange the code
# ---------------------------------------------------------------------------
async def exchange_code(code: str, verifier: str) -> str:
    """Trade the authorization code for an ID token. Returns the raw JWT."""
    payload = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }
    async with httpx.AsyncClient(timeout=settings.GOOGLE_HTTP_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(TOKEN_URL, data=payload)
        except httpx.HTTPError as exc:
            log.error("google_token_exchange_failed", error=str(exc))
            raise AppError(
                "Could not reach Google to complete sign-in",
                code=ErrorCode.INTERNAL_ERROR,
                status_code=502,
            ) from exc

    if response.status_code != 200:
        # Google's error body names the client and the redirect URI. Log it —
        # redirect_uri_mismatch is the single most common misconfiguration and
        # is invisible without this — but never return it to the caller.
        log.error(
            "google_token_exchange_rejected",
            status=response.status_code,
            body=response.text[:500],
        )
        raise UnauthorizedError("Google rejected this sign-in attempt")

    id_token = response.json().get("id_token")
    if not id_token:
        log.error("google_token_response_missing_id_token")
        raise UnauthorizedError("Google returned no identity token")
    return id_token


# ---------------------------------------------------------------------------
# Step 3 — verify the ID token
# ---------------------------------------------------------------------------
async def _fetch_jwks() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.GOOGLE_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.get(JWKS_URL)
        response.raise_for_status()
        return response.json()


async def _signing_key(kid: str) -> Any:
    """The public key for `kid`, refetching once if the cache has never seen it.

    Key rotation is the reason for the retry: a token signed with a key minted
    after our last fetch would otherwise fail verification for up to an hour,
    locking every user out of sign-in until the cache aged out.
    """
    now = time.monotonic()
    cached = _jwks_cache["keys"]
    fresh = cached is not None and (now - _jwks_cache["fetched_at"]) < _JWKS_TTL_SECONDS

    if fresh:
        try:
            return PyJWKSet.from_dict(cached)[kid].key
        except KeyError:
            pass  # unknown kid — fall through and refetch

    try:
        document = await _fetch_jwks()
    except httpx.HTTPError as exc:
        log.error("google_jwks_fetch_failed", error=str(exc))
        raise AppError(
            "Could not reach Google to verify sign-in",
            code=ErrorCode.INTERNAL_ERROR,
            status_code=502,
        ) from exc

    _jwks_cache["keys"] = document
    _jwks_cache["fetched_at"] = now
    try:
        return PyJWKSet.from_dict(document)[kid].key
    except KeyError as exc:
        log.error("google_jwks_unknown_kid", kid=kid)
        raise UnauthorizedError("Google's identity token could not be verified") from exc


async def verify_id_token(id_token: str) -> GoogleProfile:
    try:
        kid = jwt.get_unverified_header(id_token).get("kid")
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Malformed identity token") from exc
    if not kid:
        raise UnauthorizedError("Malformed identity token")

    key = await _signing_key(kid)

    try:
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=["RS256"],
            # `aud` must be our own client ID: a token minted for a different
            # application is a valid Google token and an invalid login here.
            audience=settings.GOOGLE_CLIENT_ID,
            issuer=ISSUERS,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        log.warning("google_id_token_invalid", error=str(exc))
        raise UnauthorizedError("Google's identity token could not be verified") from exc

    email = claims.get("email")
    if not email:
        # Only reachable if the `email` scope were dropped from SCOPES; without
        # an address there is no way to link or create an account.
        raise UnauthorizedError("Google did not return an email address")

    return GoogleProfile(
        subject=str(claims["sub"]),
        email=email,
        # Google sends this as a real bool, but has historically sent the
        # string "true" to some clients. Coerce rather than trust the type —
        # a truthy "false" string would defeat the linking guard entirely.
        email_verified=str(claims.get("email_verified", False)).lower() == "true",
        full_name=claims.get("name"),
        avatar_url=claims.get("picture"),
    )
