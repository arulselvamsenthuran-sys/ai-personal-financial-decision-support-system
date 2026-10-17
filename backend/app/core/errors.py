"""Phase 22 — Centralised API error handling.

Changes from Phase 21:
- Unhandled 500 errors now include the correlation request_id in the response
  so operations can cross-reference the structured log entry.
- Internal exception details, stack traces, SQL, and credentials are never
  returned to clients.
- AppError responses retain their existing shape.
- Expected validation/auth/rate-limit errors are not logged as server failures.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.correlation import get_request_id
from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base application error.

    Subclass this for domain-specific errors in future phases.
    """

    def __init__(
        self,
        message: str = "An unexpected error occurred.",
        status_code: int = 500,
    ) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach global exception handlers to the FastAPI app."""

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "AppError: %s (status=%d)",
            exc.message,
            exc.status_code,
            extra={"event": "http.request.failed", "status_code": exc.status_code},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected server errors safely.

        - Logs full traceback internally (for operations/devs) with correlation ID.
        - Returns a generic, safe message to the client — no stack traces, SQL, or secrets.
        - Includes the request_id so clients can report it and ops can trace the log.
        """
        request_id = (
            get_request_id()
            or getattr(request.state, "request_id", None)
            or request.headers.get("X-Request-ID")
        )
        logger.exception(
            "Unhandled exception — request_id=%s: %s",
            request_id,
            type(exc).__name__,
            extra={"event": "http.request.failed", "status_code": 500, "request_id": request_id},
        )
        body: dict = {"detail": "Internal server error."}
        if request_id:
            body["request_id"] = request_id
        response = JSONResponse(status_code=500, content=body)
        if request_id:
            response.headers["X-Request-ID"] = request_id
        return response
