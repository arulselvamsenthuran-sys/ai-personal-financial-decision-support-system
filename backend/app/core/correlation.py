"""Phase 22 — Correlation ID management using contextvars.

Provides request-scoped correlation IDs for HTTP requests and background jobs.
IDs are isolated per concurrent request via Python's contextvars.

Security Rules:
- Client-supplied X-Request-ID values are validated for format and length.
- Never used for authentication or authorization.
- Context is cleared after each request to prevent leakage between concurrent requests.
"""

from __future__ import annotations

import re
import secrets
import uuid
from contextvars import ContextVar

# ---------------------------------------------------------------------------
# ContextVar — stores the current request/job correlation ID
# ---------------------------------------------------------------------------

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# ---------------------------------------------------------------------------
# Format validation
# ---------------------------------------------------------------------------

# Allow UUID (hex + hyphens), alphanumeric + hyphens/underscores; 8-72 chars
_VALID_CORRELATION_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{8,72}$")

_MAX_CLIENT_ID_LENGTH = 72


def _is_valid_client_id(value: str) -> bool:
    """Return True if the client-supplied ID meets format/length requirements."""
    if not value or len(value) > _MAX_CLIENT_ID_LENGTH:
        return False
    return bool(_VALID_CORRELATION_ID_RE.match(value))


def generate_request_id() -> str:
    """Generate a cryptographically random correlation ID."""
    return secrets.token_hex(16)  # 32 hex chars


def validate_or_generate(client_id: str | None) -> str:
    """Accept a client-supplied ID if valid; otherwise generate a new one.

    Never raises; always returns a usable identifier.
    """
    if client_id and _is_valid_client_id(client_id):
        return client_id
    return generate_request_id()


# ---------------------------------------------------------------------------
# Context accessors
# ---------------------------------------------------------------------------

def set_request_id(request_id: str) -> None:
    """Store the current request ID in context."""
    _request_id_var.set(request_id)


def get_request_id() -> str | None:
    """Return the current request ID, or None if not in a request context."""
    return _request_id_var.get(None)


def clear_request_id() -> None:
    """Clear the current request ID from context (call after request completes)."""
    _request_id_var.set(None)


def make_job_correlation_id(job_id: uuid.UUID, initiating_request_id: str | None = None) -> str:
    """Build a correlation ID for a background job execution.

    If the job was triggered by an HTTP request, include the request ID for traceability.
    Scheduled jobs will only carry their own job ID.
    """
    base = f"job-{job_id}"
    if initiating_request_id:
        return f"{base}|req-{initiating_request_id}"
    return base
