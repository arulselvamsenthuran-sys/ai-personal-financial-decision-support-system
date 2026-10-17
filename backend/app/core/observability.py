"""Phase 22 — Process-local operational observability.

Tracks in-memory counters for worker and scheduler health.

IMPORTANT LIMITATIONS:
- All counters are process-local and reset on application restart.
- Not aggregated across multiple worker processes or instances.
- Not a substitute for persistent monitoring or alerting infrastructure.
- Metric labels use only bounded, safe values (no user IDs, job IDs, financial data).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Worker Metrics
# ---------------------------------------------------------------------------

class _WorkerMetrics:
    """Thread-safe process-local counters for the background job worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._completed: int = 0
        self._failed: int = 0
        self._cancelled: int = 0
        self._last_completed_at: datetime | None = None
        self._last_error_at: datetime | None = None
        self._last_error_category: str | None = None
        self._orphans_reconciled_running: int = 0
        self._orphans_recovered_queued: int = 0

    # ---- Mutators ----

    def record_completed(self) -> None:
        with self._lock:
            self._completed += 1
            self._last_completed_at = datetime.now(timezone.utc)

    def record_failed(self, error_category: str = "unknown") -> None:
        with self._lock:
            self._failed += 1
            self._last_error_at = datetime.now(timezone.utc)
            self._last_error_category = error_category

    def record_cancelled(self) -> None:
        with self._lock:
            self._cancelled += 1

    def record_startup_reconciliation(self, failed_running: int, recovered_queued: int) -> None:
        with self._lock:
            self._orphans_reconciled_running += failed_running
            self._orphans_recovered_queued += recovered_queued

    # ---- Readers ----

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "jobs_completed_since_start": self._completed,
                "jobs_failed_since_start": self._failed,
                "jobs_cancelled_since_start": self._cancelled,
                "last_completed_at": self._last_completed_at.isoformat() if self._last_completed_at else None,
                "last_error_at": self._last_error_at.isoformat() if self._last_error_at else None,
                "last_error_category": self._last_error_category,
                "orphans_reconciled_running_on_startup": self._orphans_reconciled_running,
                "orphans_recovered_queued_on_startup": self._orphans_recovered_queued,
            }


# ---------------------------------------------------------------------------
# Scheduler Metrics
# ---------------------------------------------------------------------------

class _SchedulerMetrics:
    """Thread-safe process-local counters for the monitoring scheduler."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cycles_succeeded: int = 0
        self._cycles_failed: int = 0
        self._jobs_enqueued: int = 0
        self._last_poll_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error_at: datetime | None = None
        self._last_error_category: str | None = None

    # ---- Mutators ----

    def record_poll(self) -> None:
        with self._lock:
            self._last_poll_at = datetime.now(timezone.utc)

    def record_cycle_success(self, jobs_enqueued: int = 0) -> None:
        with self._lock:
            self._cycles_succeeded += 1
            self._jobs_enqueued += jobs_enqueued
            self._last_success_at = datetime.now(timezone.utc)

    def record_cycle_failure(self, error_category: str = "unknown") -> None:
        with self._lock:
            self._cycles_failed += 1
            self._last_error_at = datetime.now(timezone.utc)
            self._last_error_category = error_category

    # ---- Readers ----

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "scheduler_cycles_succeeded": self._cycles_succeeded,
                "scheduler_cycles_failed": self._cycles_failed,
                "jobs_enqueued_by_scheduler": self._jobs_enqueued,
                "last_poll_at": self._last_poll_at.isoformat() if self._last_poll_at else None,
                "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
                "last_error_at": self._last_error_at.isoformat() if self._last_error_at else None,
                "last_error_category": self._last_error_category,
            }


# ---------------------------------------------------------------------------
# HTTP Request Metrics
# ---------------------------------------------------------------------------

class _RequestMetrics:
    """Thread-safe process-local HTTP request counters.

    Labels use only normalized route template, HTTP method, and status class (2xx, 4xx, 5xx).
    Never include raw paths, user IDs, or financial data.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key: (method, route_template, status_class) → count
        self._counts: dict[tuple[str, str, str], int] = {}
        self._total: int = 0

    def record(self, method: str, route_template: str, status_code: int) -> None:
        status_class = f"{status_code // 100}xx"
        key = (method.upper(), route_template, status_class)
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1
            self._total += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_requests": self._total,
                "by_route": [
                    {
                        "method": k[0],
                        "route": k[1],
                        "status_class": k[2],
                        "count": v,
                    }
                    for k, v in sorted(self._counts.items())
                ],
            }


# ---------------------------------------------------------------------------
# Singleton instances
# ---------------------------------------------------------------------------

worker_metrics = _WorkerMetrics()
scheduler_metrics = _SchedulerMetrics()
request_metrics = _RequestMetrics()
