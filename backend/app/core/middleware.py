"""Phase 22 — HTTP Request Middleware.

Provides:
1. Correlation ID injection: reads X-Request-ID, validates it, or generates one.
2. Structured request logging (http.request.completed / http.request.failed).
3. Health-check request suppression at INFO level.
4. Request duration measurement.
5. X-Request-ID response header injection.
6. Observability metrics recording.

Security Rules:
- Never logs request bodies, response bodies, cookies, or auth headers.
- Never logs raw URL paths containing user-supplied identifiers.
- Health-check requests are logged at DEBUG to reduce log noise.
- Correlation IDs are never used for authentication or authorization.
- Context is cleared after each request.
"""

from __future__ import annotations

import time
import logging
from contextvars import copy_context

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from app.core.correlation import (
    clear_request_id,
    get_request_id,
    set_request_id,
    validate_or_generate,
)
from app.core.observability import request_metrics

logger = logging.getLogger(__name__)

# Routes that are logged at DEBUG to avoid flooding logs with health-check noise
_SILENT_PREFIXES = ("/api/health",)


def _get_route_template(request: Request) -> str:
    """Extract the normalized route template (e.g., /api/jobs/{job_id}).

    Falls back to the sanitized path prefix if no route matches,
    ensuring no raw user-supplied IDs appear in metric labels.
    """
    try:
        for route in request.app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                return getattr(route, "path", request.url.path)
    except Exception:
        pass
    # Fallback: return only the first two path segments to bound cardinality
    parts = request.url.path.rstrip("/").split("/")
    return "/" + "/".join(parts[1:3]) if len(parts) > 2 else request.url.path


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware that attaches a correlation ID to each request and logs it."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        # 1. Determine request ID
        client_supplied = request.headers.get("X-Request-ID")
        request_id = validate_or_generate(client_supplied)
        set_request_id(request_id)
        try:
            request.state.request_id = request_id
        except Exception:
            pass

        is_health_check = any(
            request.url.path.startswith(p) for p in _SILENT_PREFIXES
        )

        start_time = time.perf_counter()
        status_code = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # Exception handlers registered on the app will produce the response;
            # this branch handles truly uncaught exceptions before they reach handlers.
            logger.exception(
                "Unhandled exception in middleware dispatch",
                extra={"event": "http.request.failed"},
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            route_template = _get_route_template(request)

            log_level = logging.DEBUG if is_health_check else logging.INFO
            event_name = (
                "http.request.failed" if status_code >= 500 else "http.request.completed"
            )

            logger.log(
                log_level,
                "%s %s → %d",
                request.method,
                route_template,
                status_code,
                extra={
                    "event": event_name,
                    "http_method": request.method,
                    "route": route_template,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )

            # Record to in-memory metrics (only if not an internal health check,
            # to prevent cardinality noise from frequent polling)
            if not is_health_check:
                request_metrics.record(request.method, route_template, status_code)

            # Inject correlation ID into response header
            if response is not None:
                response.headers["X-Request-ID"] = request_id

            # Clean up context to prevent leakage between concurrent requests
            clear_request_id()

        return response
