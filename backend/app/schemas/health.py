"""Phase 22 — Pydantic response schemas for health and diagnostics endpoints."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response for GET /api/health (liveness check)."""

    status: str


class DBHealthResponse(BaseModel):
    """Response for GET /api/health/db."""

    status: str
    database: str


class ReadinessResponse(BaseModel):
    """Response for GET /api/health/ready (full readiness check)."""

    status: str          # "ready" or "not_ready"
    database: str        # "connected" or "disconnected"
    message: str | None = None


class WorkerHealthResponse(BaseModel):
    """Response for GET /api/health/worker (background job worker diagnostics).

    All metrics are process-local and reset on restart.
    """

    worker_running: bool
    worker_shutting_down: bool
    queue_depth: int
    jobs_completed_since_start: int
    jobs_failed_since_start: int
    jobs_cancelled_since_start: int
    last_completed_at: str | None
    last_error_at: str | None
    last_error_category: str | None
    orphans_reconciled_running_on_startup: int
    orphans_recovered_queued_on_startup: int
    note: str = "All counters are process-local and reset on application restart."


class SchedulerHealthResponse(BaseModel):
    """Response for GET /api/health/scheduler (monitoring scheduler diagnostics).

    All metrics are process-local and reset on restart.
    """

    scheduler_running: bool
    scheduler_shutting_down: bool
    scheduler_cycles_succeeded: int
    scheduler_cycles_failed: int
    jobs_enqueued_by_scheduler: int
    last_poll_at: str | None
    last_success_at: str | None
    last_error_at: str | None
    last_error_category: str | None
    note: str = "All counters are process-local and reset on application restart."
