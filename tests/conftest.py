"""Test fixtures.

Settings are injected before any app module is imported, so tests never depend
on a developer's local .env and CI needs no secret provisioning.
"""

import os

os.environ.setdefault("ENVIRONMENT", "test")
# Host port 5433 by default — 5432 is very often taken by another project's
# database. Override with DATABASE_URL if yours differs.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://crshop:crshop@localhost:5433/crshop_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET_KEY", "t" * 64)
os.environ.setdefault("RIDER_PIN_PEPPER", "p" * 64)
os.environ.setdefault("OTP_PEPPER", "o" * 64)
os.environ.setdefault("TOTP_ENCRYPTION_KEY", "k" * 64)

# FORCED, not setdefault. `Settings` also reads .env, and a developer with a
# real RESEND_API_KEY there would otherwise have the whole suite firing live
# requests at Resend on every OTP — burning the 100/day free-tier quota, adding
# a network round trip per test, and failing anyway because Resend rejects
# @example.com recipients. Tests must not touch a third party.
os.environ["RESEND_API_KEY"] = ""

import uuid  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest.fixture
async def client():
    """ASGI client that never opens a network socket."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_available() -> bool:
    """Skip DB-backed tests cleanly when no database is running."""
    from app.core.database import check_database

    try:
        await check_database()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"database unavailable: {exc}")
    return True


@pytest.fixture
async def customer_user(db_available):
    """A real CUSTOMER row, removed afterwards.

    Created through the ORM rather than raw SQL so the models themselves are
    exercised — a mapping error surfaces here rather than in Step 4.
    """
    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.user import User

    user = User(
        id=uuid.uuid4(),
        role="CUSTOMER",
        email=f"test-{uuid.uuid4().hex[:12]}@example.com",
        full_name="Test Customer",
    )
    async with SessionLocal() as session:
        session.add(user)
        await session.commit()

    yield user

    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest.fixture
def customer_token(customer_user) -> str:
    from app.core.security import create_access_token

    return create_access_token(str(customer_user.id), customer_user.role)


@pytest.fixture
async def cleanup_users():
    """Remove users created by identifier during a test, plus their OTP rows.

    Registered eagerly (before the request that creates the user) so a failing
    assertion mid-test still leaves the database clean for the next run.
    """
    identifiers: list[str] = []

    def register(identifier: str) -> str:
        identifiers.append(identifier)
        return identifier

    yield register

    from sqlalchemy import delete, or_, select

    from app.core.database import SessionLocal
    from app.models.restaurant import Restaurant
    from app.models.user import OtpCode, User

    async with SessionLocal() as session:
        for ident in identifiers:
            await session.execute(delete(OtpCode).where(OtpCode.identifier == ident))
            # restaurants.owner_id is ON DELETE RESTRICT — a vendor who owns a
            # storefront cannot be deleted until it is. That is correct
            # behaviour (it protects order history), so the fixture unwinds in
            # the same order the application would have to.
            result = await session.execute(
                select(User.id).where(or_(User.email == ident, User.phone == ident))
            )
            for (user_id,) in result.all():
                await session.execute(delete(Restaurant).where(Restaurant.owner_id == user_id))
            await session.execute(
                delete(User).where(or_(User.email == ident, User.phone == ident))
            )
        await session.commit()


@pytest.fixture(autouse=True)
async def flush_rate_limit_keys():
    """OTP cooldowns live in Redis and would otherwise leak between tests,
    turning an unrelated test into a spurious 429."""
    yield
    from app.core.redis import get_redis

    redis = get_redis()
    keys = [k async for k in redis.scan_iter("otp:cooldown:*")]
    if keys:
        await redis.delete(*keys)


@pytest.fixture
async def reset_limits():
    """Clear login/OTP rate-limit counters around a test.

    Cleared BEFORE as well as after: these keys are per-identifier and per-IP,
    and every test shares one loopback IP, so leakage from an earlier test would
    otherwise produce a spurious 429 here.
    """
    from app.core.redis import get_redis

    async def _clear():
        redis = get_redis()
        keys = [k async for k in redis.scan_iter("rl:*")]
        if keys:
            await redis.delete(*keys)

    await _clear()
    yield
    await _clear()


@pytest.fixture
async def clear_cooldowns():
    """Clear the OTP resend cooldown on demand.

    A few tests legitimately need two codes for one address in quick
    succession — registering as a customer then attempting a vendor signup, for
    example. The 60-second cooldown is correct behaviour, so rather than weaken
    it, those tests skip it explicitly.
    """
    from app.core.redis import get_redis

    async def _clear():
        redis = get_redis()
        keys = [k async for k in redis.scan_iter("otp:cooldown:*")]
        if keys:
            await redis.delete(*keys)

    return _clear
