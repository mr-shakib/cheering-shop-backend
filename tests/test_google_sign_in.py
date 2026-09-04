"""Sign in with Google — the authorization-code flow end to end.

Nothing here talks to Google. The two outbound calls (token exchange and JWKS
fetch) are replaced, and the ID-token tests sign their own JWTs with a locally
generated RSA key so `verify_id_token` runs its real verification against a
real signature rather than a stub that always says yes.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import oauth_service

AUTHORIZE = "/api/v1/auth/google/authorize"
CALLBACK = "/api/v1/auth/google/callback"


# ---------------------------------------------------------------------------
# A local signing key, so token verification is exercised for real
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def google_jwks(signing_key, monkeypatch):
    """Serve our own public key as Google's JWKS, and reset the module cache."""
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    public_jwk.update({"kid": "test-kid", "use": "sig", "alg": "RS256"})
    document = {"keys": [public_jwk]}

    async def _fake_fetch():
        return document

    monkeypatch.setattr(oauth_service, "_fetch_jwks", _fake_fetch)
    # The cache is module state and would otherwise leak a real key between
    # tests — or, worse, let a test pass on a stale entry.
    monkeypatch.setattr(oauth_service, "_jwks_cache", {"fetched_at": 0.0, "keys": None})
    return document


def make_id_token(signing_key, **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id.apps.googleusercontent.com",
        "sub": f"google-sub-{uuid.uuid4().hex[:12]}",
        "email": f"gtest-{uuid.uuid4().hex[:10]}@example.com",
        "email_verified": True,
        "name": "Google Person",
        "picture": "https://lh3.googleusercontent.com/a/default",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-kid"})


# ---------------------------------------------------------------------------
# Step 1 — /authorize
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("reset_limits")
async def test_authorize_redirects_to_google_with_pkce(client):
    response = await client.get(AUTHORIZE)

    assert response.status_code == 307
    target = urlparse(response.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == oauth_service.AUTHORIZE_URL

    params = parse_qs(target.query)
    assert params["client_id"] == ["test-client-id.apps.googleusercontent.com"]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["openid email profile"]
    # PKCE is the control that makes an intercepted redirect useless. If this
    # assertion ever goes, so does the security of the whole flow.
    assert params["code_challenge_method"] == ["S256"]
    assert len(params["code_challenge"][0]) >= 43
    assert params["state"][0]


@pytest.mark.usefixtures("reset_limits")
async def test_authorize_stores_the_verifier_server_side(client):
    """The verifier must never appear in anything the client can see."""
    from app.core.redis import get_redis

    response = await client.get(AUTHORIZE)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]

    stored = json.loads(await get_redis().get(f"{oauth_service._STATE_PREFIX}{state}"))
    assert stored["verifier"]
    assert stored["verifier"] not in response.headers["location"]
    assert stored["redirect"] == "crshop://auth/callback"


@pytest.mark.usefixtures("reset_limits")
async def test_authorize_accepts_an_allowlisted_redirect(client):
    response = await client.get(AUTHORIZE, params={"redirect": "crshop://auth/callback"})
    assert response.status_code == 307


@pytest.mark.usefixtures("reset_limits")
@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example.com/steal",
        # Shares a prefix with the allowed value — the reason membership is
        # tested by equality and not startswith().
        "crshop://auth/callback.evil.com",
        "crshop://auth/callbackx",
    ],
)
async def test_authorize_refuses_an_unlisted_redirect(client, hostile):
    """An unchecked redirect target here is an open redirect that hands the
    caller somebody else's session tokens."""
    response = await client.get(AUTHORIZE, params={"redirect": hostile})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# Step 2 — /callback state handling
# ---------------------------------------------------------------------------
async def test_callback_rejects_an_unknown_state(client):
    response = await client.get(CALLBACK, params={"code": "x", "state": "never-issued"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_callback_requires_state(client):
    response = await client.get(CALLBACK, params={"code": "x"})
    assert response.status_code == 400


@pytest.mark.usefixtures("reset_limits")
async def test_state_is_single_use(client, monkeypatch, signing_key, google_jwks, cleanup_users):
    """A replayed callback must not mint a second session."""
    email = cleanup_users(f"gtest-{uuid.uuid4().hex[:10]}@example.com")

    async def _fake_exchange(code, verifier):
        return make_id_token(signing_key, email=email)

    monkeypatch.setattr(oauth_service, "exchange_code", _fake_exchange)

    state = parse_qs(urlparse((await client.get(AUTHORIZE)).headers["location"]).query)["state"][0]

    first = await client.get(CALLBACK, params={"code": "auth-code", "state": state})
    assert first.status_code == 307
    assert first.headers["location"].startswith("crshop://auth/callback#")

    second = await client.get(CALLBACK, params={"code": "auth-code", "state": state})
    assert second.status_code == 401


@pytest.mark.usefixtures("reset_limits")
async def test_user_cancelling_consent_is_deep_linked_back(client):
    """Otherwise the app's spinner never stops."""
    state = parse_qs(urlparse((await client.get(AUTHORIZE)).headers["location"]).query)["state"][0]

    response = await client.get(CALLBACK, params={"state": state, "error": "access_denied"})

    assert response.status_code == 307
    assert response.headers["location"] == "crshop://auth/callback#error=access_denied"


# ---------------------------------------------------------------------------
# Step 3 — ID token verification
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("google_jwks")
async def test_valid_id_token_yields_a_profile(signing_key):
    profile = await oauth_service.verify_id_token(make_id_token(signing_key, sub="abc123"))

    assert profile.subject == "abc123"
    assert profile.email_verified is True
    assert profile.full_name == "Google Person"


@pytest.mark.usefixtures("google_jwks")
async def test_id_token_for_another_application_is_refused(signing_key):
    """A token minted for a different `aud` is a perfectly valid Google token
    and an invalid login here. Without the audience check, any developer with
    a Google client could sign in as anyone."""
    from app.core.errors import UnauthorizedError

    token = make_id_token(signing_key, aud="someone-elses-client.apps.googleusercontent.com")

    with pytest.raises(UnauthorizedError):
        await oauth_service.verify_id_token(token)


@pytest.mark.usefixtures("google_jwks")
async def test_id_token_from_the_wrong_issuer_is_refused(signing_key):
    from app.core.errors import UnauthorizedError

    with pytest.raises(UnauthorizedError):
        await oauth_service.verify_id_token(make_id_token(signing_key, iss="https://evil.example"))


@pytest.mark.usefixtures("google_jwks")
async def test_expired_id_token_is_refused(signing_key):
    from app.core.errors import UnauthorizedError

    stale = datetime.now(UTC) - timedelta(hours=2)
    token = make_id_token(signing_key, iat=stale, exp=stale + timedelta(minutes=5))

    with pytest.raises(UnauthorizedError):
        await oauth_service.verify_id_token(token)


@pytest.mark.usefixtures("google_jwks")
async def test_token_signed_by_the_wrong_key_is_refused(signing_key):
    """The signature check is the only thing standing between a forged `sub`
    and a session for any account."""
    from app.core.errors import UnauthorizedError

    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": "test-client-id.apps.googleusercontent.com",
            "sub": "victim-sub",
            "email": "victim@example.com",
            "email_verified": True,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        impostor,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )

    with pytest.raises(UnauthorizedError):
        await oauth_service.verify_id_token(forged)


# ---------------------------------------------------------------------------
# Account resolution
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("reset_limits")
async def test_first_sign_in_creates_a_verified_customer(
    client, monkeypatch, signing_key, google_jwks, cleanup_users, db_available
):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.user import AuthIdentity, User

    email = cleanup_users(f"gtest-{uuid.uuid4().hex[:10]}@example.com")
    subject = f"sub-{uuid.uuid4().hex[:12]}"

    async def _fake_exchange(code, verifier):
        return make_id_token(signing_key, email=email, sub=subject)

    monkeypatch.setattr(oauth_service, "exchange_code", _fake_exchange)

    state = parse_qs(urlparse((await client.get(AUTHORIZE)).headers["location"]).query)["state"][0]
    response = await client.get(CALLBACK, params={"code": "c", "state": state})

    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("crshop://auth/callback#")
    fragment = parse_qs(location.split("#", 1)[1])
    assert fragment["token_type"] == ["Bearer"]
    # The tokens must ride in the fragment, which is never sent to a server and
    # stays out of proxy logs and browser history sync.
    assert "access_token" not in urlparse(location).query

    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        assert user.role == "CUSTOMER"
        assert user.is_email_verified is True
        assert user.password_hash is None
        assert user.full_name == "Google Person"

        link = (
            await session.execute(select(AuthIdentity).where(AuthIdentity.subject == subject))
        ).scalar_one()
        assert link.provider == "google"
        assert link.user_id == user.id

    # The issued access token is a normal session — it opens /users/me.
    me = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {fragment['access_token'][0]}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["email"] == email


@pytest.mark.usefixtures("reset_limits")
async def test_google_links_to_an_existing_account_rather_than_duplicating_it(
    client, monkeypatch, signing_key, google_jwks, customer_user
):
    """A verified Google email proves control of the mailbox — the same proof
    the OTP flow demands — so the accounts merge instead of forking."""
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models.user import AuthIdentity, User

    async def _fake_exchange(code, verifier):
        return make_id_token(signing_key, email=customer_user.email)

    monkeypatch.setattr(oauth_service, "exchange_code", _fake_exchange)

    state = parse_qs(urlparse((await client.get(AUTHORIZE)).headers["location"]).query)["state"][0]
    response = await client.get(CALLBACK, params={"code": "c", "state": state})
    assert response.status_code == 307

    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(User).where(User.email == customer_user.email)
        )
        assert count == 1, "a second account was created instead of linking"

        link = (
            await session.execute(
                select(AuthIdentity).where(AuthIdentity.user_id == customer_user.id)
            )
        ).scalar_one()
        assert link.provider == "google"

    fragment = parse_qs(response.headers["location"].split("#", 1)[1])
    me = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {fragment['access_token'][0]}"},
    )
    assert me.json()["data"]["id"] == str(customer_user.id)


@pytest.mark.usefixtures("reset_limits")
async def test_unverified_google_email_cannot_link_or_create(
    client, monkeypatch, signing_key, google_jwks, customer_user
):
    """The verified claim is the entire basis for auto-linking. Accepting an
    unverified one would hand over any account whose email can be guessed."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.user import AuthIdentity

    async def _fake_exchange(code, verifier):
        return make_id_token(signing_key, email=customer_user.email, email_verified=False)

    monkeypatch.setattr(oauth_service, "exchange_code", _fake_exchange)

    state = parse_qs(urlparse((await client.get(AUTHORIZE)).headers["location"]).query)["state"][0]
    response = await client.get(CALLBACK, params={"code": "c", "state": state})

    assert response.status_code == 400
    async with SessionLocal() as session:
        linked = (
            await session.execute(
                select(AuthIdentity).where(AuthIdentity.user_id == customer_user.id)
            )
        ).scalar_one_or_none()
        assert linked is None


@pytest.mark.usefixtures("reset_limits")
async def test_email_verified_sent_as_a_string_is_read_correctly(
    client, monkeypatch, signing_key, google_jwks, customer_user
):
    """Google has historically sent this claim as "true"/"false" rather than a
    bool. A truthy "false" string would defeat the guard above entirely."""
    async def _fake_exchange(code, verifier):
        return make_id_token(signing_key, email=customer_user.email, email_verified="false")

    monkeypatch.setattr(oauth_service, "exchange_code", _fake_exchange)

    state = parse_qs(urlparse((await client.get(AUTHORIZE)).headers["location"]).query)["state"][0]
    assert (await client.get(CALLBACK, params={"code": "c", "state": state})).status_code == 400


@pytest.mark.usefixtures("reset_limits")
async def test_a_deactivated_account_cannot_sign_in_with_google(
    client, monkeypatch, signing_key, google_jwks, customer_user
):
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.user import User

    async with SessionLocal() as session:
        await session.execute(
            update(User).where(User.id == customer_user.id).values(is_active=False)
        )
        await session.commit()

    async def _fake_exchange(code, verifier):
        return make_id_token(signing_key, email=customer_user.email)

    monkeypatch.setattr(oauth_service, "exchange_code", _fake_exchange)

    state = parse_qs(urlparse((await client.get(AUTHORIZE)).headers["location"]).query)["state"][0]
    assert (await client.get(CALLBACK, params={"code": "c", "state": state})).status_code == 401


@pytest.mark.usefixtures("reset_limits")
async def test_signing_in_twice_reuses_the_same_account(
    client, monkeypatch, signing_key, google_jwks, cleanup_users, db_available
):
    """The second sign-in matches on `sub`, so a user who changed their Google
    address still lands on the same account."""
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models.user import AuthIdentity, User

    email = cleanup_users(f"gtest-{uuid.uuid4().hex[:10]}@example.com")
    renamed = cleanup_users(f"gtest-{uuid.uuid4().hex[:10]}@example.com")
    subject = f"sub-{uuid.uuid4().hex[:12]}"
    addresses = iter([email, renamed])

    async def _fake_exchange(code, verifier):
        return make_id_token(signing_key, email=next(addresses), sub=subject)

    monkeypatch.setattr(oauth_service, "exchange_code", _fake_exchange)

    for _ in range(2):
        state = parse_qs(
            urlparse((await client.get(AUTHORIZE)).headers["location"]).query
        )["state"][0]
        assert (await client.get(CALLBACK, params={"code": "c", "state": state})).status_code == 307

    async with SessionLocal() as session:
        links = await session.scalar(
            select(func.count()).select_from(AuthIdentity).where(AuthIdentity.subject == subject)
        )
        assert links == 1
        users = await session.scalar(
            select(func.count()).select_from(User).where(User.email.in_([email, renamed]))
        )
        assert users == 1


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("reset_limits")
async def test_endpoints_report_501_when_google_is_not_configured(client, monkeypatch):
    """A deployment with no Google project must fail loudly and specifically,
    not with a 404 that reads like a routing bug."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")

    response = await client.get(AUTHORIZE)

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"


@pytest.mark.usefixtures("reset_limits")
async def test_authorize_is_rate_limited_per_ip(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_AUTHORIZE_MAX_PER_HOUR", 3)

    for _ in range(3):
        assert (await client.get(AUTHORIZE)).status_code == 307

    limited = await client.get(AUTHORIZE)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


async def test_security_state_reports_linked_providers(client, customer_token):
    response = await client.get(
        "/api/v1/users/me/security", headers={"Authorization": f"Bearer {customer_token}"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["linked_providers"] == []
