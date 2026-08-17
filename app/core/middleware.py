"""Request-scoped middleware: correlation IDs, access logs, security headers."""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.client import client_ip
from app.core.config import settings

log = structlog.get_logger()

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a correlation id to every request, log, and response.

    Without this, a production incident gives you a pile of log lines with no
    way to tell which belong to the same request — and no way for a user
    reporting "it failed at 14:32" to hand you anything you can search on.

    An inbound `X-Request-ID` is honoured so a trace survives across services
    (and Traefik, if you configure it to inject one); otherwise one is minted.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]

        # structlog contextvars: every log emitted downstream in this request —
        # including inside services — carries the id without being passed it.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers turn this into the standard envelope; log
            # the timing here so failed requests appear in the access log too.
            log.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                client=client_ip(request),
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id

        # Health checks run every 30s per container; logging them buries real
        # traffic and costs money in any hosted log service.
        if not request.url.path.startswith("/health"):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                client=client_ip(request),
            )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Defence-in-depth headers.

    Set in the application rather than the proxy so they hold regardless of what
    fronts it. The bare-metal deployment puts these in Caddy; the Dokploy one
    uses Traefik, which does not add them by default — so an API deployed the
    second way would silently lose them.
    """

    # Swagger UI and ReDoc load their own JavaScript and CSS from a CDN, which
    # `default-src 'none'` forbids. They are decided BEFORE the header is set
    # rather than removed afterwards: Starlette's MutableHeaders has no .pop(),
    # so the obvious "set then remove" spelling raises AttributeError and turns
    # every docs request into a 500.
    CSP_EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        # This API returns JSON, never HTML with scripts, so everywhere else the
        # policy can be maximally restrictive.
        if request.url.path not in self.CSP_EXEMPT_PATHS:
            response.headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        # Browsers should not cache authenticated payloads.
        if request.url.path.startswith(settings.API_V1_PREFIX):
            response.headers.setdefault("Cache-Control", "no-store")

        # HSTS in production only. Setting it in local development would pin
        # localhost to HTTPS in your browser for a year — a genuinely annoying
        # thing to undo.
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

        return response
