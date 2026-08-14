"""Application entrypoint."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import check_database, dispose_engine
from app.core.errors import register_exception_handlers
from app.core.redis import check_redis, close_redis
from app.core.responses import ok

log = structlog.get_logger()


def _configure_logging() -> None:
    logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Human-readable locally, JSON in deployed environments so log
            # aggregators can index fields rather than regex over strings.
            structlog.dev.ConsoleRenderer()
            if settings.ENVIRONMENT == "local"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.DEBUG else logging.INFO
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    _configure_logging()
    log.info("starting", environment=settings.ENVIRONMENT, version=app.version)
    yield
    log.info("shutting_down")
    await dispose_engine()
    await close_redis()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description=(
        "Food delivery backend implementing cr-shop-backend-api-specification.md v1.0.0.\n\n"
        "All responses use the envelope from spec §2: `{success, data, meta}` on "
        "success, `{success, error:{code, message, details}}` on failure."
    ),
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

register_exception_handlers(app)

# Spec §2: every endpoint lives under /api/v1
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["System"], summary="Liveness probe")
async def health() -> dict:
    """Cheap and dependency-free — answers "is the process up", nothing more."""
    return ok({"status": "ok", "environment": settings.ENVIRONMENT})


@app.get("/health/ready", tags=["System"], summary="Readiness probe")
async def readiness() -> JSONResponse:
    """Checks the dependencies a request actually needs.

    Redis is treated as required, not optional (decision D2): without it live
    tracking and rider dispatch do not work, so a node that cannot reach Redis
    should not receive traffic.
    """
    checks: dict[str, object] = {}
    healthy = True

    for name, probe in (("database", check_database), ("redis", check_redis)):
        try:
            detail = await probe()
            # Version strings and connection errors are useful locally and are
            # reconnaissance material on a public endpoint. Outside local
            # development this reports liveness only — an orchestrator needs the
            # status code, not the PostGIS build flags.
            checks[name] = detail if settings.ENVIRONMENT == "local" else {"status": "ok"}
        except Exception as exc:
            healthy = False
            log.error("readiness_probe_failed", dependency=name, error=str(exc))
            checks[name] = {
                "status": "error",
                **({"detail": str(exc)} if settings.ENVIRONMENT == "local" else {}),
            }

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "success": healthy,
            "data": {"status": "ready" if healthy else "degraded", **checks},
        },
    )
