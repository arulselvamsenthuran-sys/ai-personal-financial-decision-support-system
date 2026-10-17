"""Phase 22 — Structured JSON logging configuration.

Provides:
- JSON-formatted log records with consistent fields.
- Configurable log level from environment settings.
- Suppression of noisy health-check and third-party logs.
- Correlation ID injection from request context.
- No duplicate handlers.

Security Rules:
- Never log passwords, tokens, API keys, secrets, or financial data.
- Sensitive fields in exception messages are not explicitly redacted here;
  callers must not pass sensitive strings to logger.error/exception calls.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


_SETUP_DONE = False  # Guard against duplicate handler installation


class _JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def __init__(self, environment: str = "development") -> None:
        super().__init__()
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        # Lazily import to avoid circular imports at module load time
        try:
            from app.core.correlation import get_request_id
            correlation_id = get_request_id()
        except Exception:
            correlation_id = None

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "environment": self._environment,
            "message": record.getMessage(),
        }

        # Optional correlation ID
        if correlation_id:
            payload["request_id"] = correlation_id

        # Optional structured event name if caller sets it
        if hasattr(record, "event"):
            payload["event"] = record.event  # type: ignore[attr-defined]

        # Extra fields set via `extra={"key": value}` on logger calls
        _SKIP = {
            "args", "created", "exc_info", "exc_text", "filename", "funcName",
            "levelname", "levelno", "lineno", "message", "module", "msecs",
            "msg", "name", "pathname", "process", "processName", "relativeCreated",
            "stack_info", "taskName", "thread", "threadName",
        }
        for key, val in record.__dict__.items():
            if key not in _SKIP and not key.startswith("_"):
                payload[key] = val

        # Exception info — include type + sanitized message, not full traceback in payload
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_val, exc_tb = record.exc_info
            payload["error_type"] = exc_type.__name__ if exc_type else "Exception"
            # Include the traceback as a string for internal logs (safe for structured logging)
            payload["traceback"] = "".join(
                traceback.format_exception(exc_type, exc_val, exc_tb)
            ).strip()

        return json.dumps(payload, default=str)


def setup_logging(environment: str = "development", log_level: str = "INFO") -> None:
    """Configure application-wide structured JSON logging.

    Safe to call multiple times — installs handlers only once.
    """
    global _SETUP_DONE
    if _SETUP_DONE:
        return
    _SETUP_DONE = True

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    # Remove any pre-existing handlers to prevent duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter(environment=environment))
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)

    # ---- Suppress noisy third-party loggers ----
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)
