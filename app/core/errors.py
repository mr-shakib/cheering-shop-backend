"""Error taxonomy and handlers producing the spec §2 error envelope.

    {
      "success": false,
      "error": {
        "code": "VALIDATION_FAILED",
        "message": "Invalid input provided",
        "details": ["password must be at least 8 characters"]
      }
    }

Every failure path in the application — including ones raised by FastAPI itself
and unhandled exceptions — is normalised into that shape. A client should never
receive FastAPI's default ``{"detail": ...}`` body.
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()


class ErrorCode:
    """Machine-readable codes. Clients branch on these, never on the message."""

    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

    # Domain-specific, mapped to the spec's documented failures.
    CART_RESTAURANT_CONFLICT = "CART_RESTAURANT_CONFLICT"  # §4: 409 on /cart/items
    ITEM_UNAVAILABLE = "ITEM_UNAVAILABLE"  # §4: checkout inventory check
    INVALID_RIDER_PIN = "INVALID_RIDER_PIN"  # §4: 400 on handoff
    ORDER_NOT_CANCELLABLE = "ORDER_NOT_CANCELLABLE"  # §4: only while PENDING
    TWO_FACTOR_REQUIRED = "TWO_FACTOR_REQUIRED"  # §4: login interception
    INVALID_OTP = "INVALID_OTP"
    STORE_CLOSED = "STORE_CLOSED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"  # §9: key reused, body differs


class AppError(Exception):
    """Base for every deliberate failure. Carries its own HTTP status."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = ErrorCode.VALIDATION_FAILED
    message: str = "Request could not be processed"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[str] | None = None,
        code: str | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or []
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.headers = headers
        super().__init__(self.message)

    def to_response(self) -> JSONResponse:
        body: dict[str, Any] = {
            "success": False,
            "error": {"code": self.code, "message": self.message},
        }
        if self.details:
            body["error"]["details"] = self.details
        return JSONResponse(status_code=self.status_code, content=body, headers=self.headers)


class ValidationError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = ErrorCode.VALIDATION_FAILED
    message = "Invalid input provided"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = ErrorCode.UNAUTHORIZED
    message = "Authentication required"

    def __init__(self, message: str | None = None, **kw: Any) -> None:
        kw.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message, **kw)


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = ErrorCode.FORBIDDEN
    message = "You do not have permission to perform this action"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = ErrorCode.NOT_FOUND
    message = "Resource not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = ErrorCode.CONFLICT
    message = "Request conflicts with current state"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = ErrorCode.RATE_LIMITED
    message = "Too many requests. Please try again later"


class NotImplementedYetError(AppError):
    """Raised by scaffolded routes that Step 4 will fill in.

    Deliberately explicit: an unimplemented endpoint returns a documented 501
    in the standard envelope rather than a 404 that looks like a routing bug.
    """

    status_code = status.HTTP_501_NOT_IMPLEMENTED
    code = ErrorCode.NOT_IMPLEMENTED
    message = "This endpoint is scaffolded but not yet implemented"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Flatten pydantic's structure into the spec's flat `details` string list.
        details = [
            f"{'.'.join(str(p) for p in err['loc'] if p != 'body')}: {err['msg']}"
            for err in exc.errors()
        ]
        return ValidationError(details=details).to_response()

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            409: ErrorCode.CONFLICT,
            429: ErrorCode.RATE_LIMITED,
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        return AppError(str(exc.detail), code=code, status_code=exc.status_code).to_response()

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the real error; return an opaque one. Stack traces and driver
        # messages must never reach a client.
        log.exception("unhandled_exception", path=request.url.path, error=str(exc))
        return AppError(
            "An unexpected error occurred",
            code=ErrorCode.INTERNAL_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        ).to_response()
