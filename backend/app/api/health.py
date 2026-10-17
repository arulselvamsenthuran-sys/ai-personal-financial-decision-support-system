"""Phase 22 — Health, readiness, and operational diagnostics API endpoints.

Endpoints:
  GET /api/health          — Liveness: is the process alive? (no external deps)
  GET /api/health/ready    — Readiness: can the service serve real requests?
  GET /api/health/db       — Database connectivity check (kept for compatibility)
  GET /api/health/worker   — Background job worker diagnostics (process-local)
  GET /api/health/scheduler — Monitoring scheduler diagnostics (process-local)

Security Rules:
- No credentials, hostnames, SQL, stack traces, or secrets are returned.
- Worker and scheduler endpoints expose operational metrics only — no user data.
- All counters are process-local and reset on restart (documented in responses).
- AI provider status is NOT checked on every health call to avoid live API calls.
"""

import asyncio

from fastapi import APIRouter, Response

from app.core.observability import scheduler_metrics, worker_metrics
from app.db.session import check_db_connection
from app.schemas.health import (
    DBHealthResponse,
    HealthResponse,
    ReadinessResponse,
    SchedulerHealthResponse,
    WorkerHealthResponse,
)

router = APIRouter(prefix="/api/health", tags=["Health"])

# ---------------------------------------------------------------------------
# Module-level references to the worker and scheduler asyncio tasks.
# Set by main.py after tasks are created in the lifespan context.
# ---------------------------------------------------------------------------

_worker_task: asyncio.Task | None = None
_scheduler_task: asyncio.Task | None = None
_worker_shutting_down: bool = False
_scheduler_shutting_down: bool = False


def register_worker_task(task: asyncio.Task) -> None:
    """Called by main.py so this module can inspect the worker's task state."""
    global _worker_task
    _worker_task = task


def register_scheduler_task(task: asyncio.Task) -> None:
    """Called by main.py so this module can inspect the scheduler's task state."""
    global _scheduler_task
    _scheduler_task = task


def set_worker_shutting_down(value: bool = True) -> None:
    global _worker_shutting_down
    _worker_shutting_down = value


def set_scheduler_shutting_down(value: bool = True) -> None:
    global _scheduler_shutting_down
    _scheduler_shutting_down = value


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=HealthResponse,
    summary="Liveness check — is the process alive?",
    description=(
        "Returns HTTP 200 if the application process is running. "
        "Does not check the database, AI providers, or any external dependencies."
    ),
)
async def health() -> HealthResponse:
    """Lightweight liveness check. No external dependency required."""
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness check — is the service ready to serve requests?",
    description=(
        "Checks database connectivity. Returns HTTP 200 if ready, 503 if not. "
        "Does not make live AI provider calls."
    ),
)
def health_ready(response: Response) -> ReadinessResponse:
    """Readiness check: verifies the database is reachable before admitting traffic."""
    connected = check_db_connection()
    if connected:
        return ReadinessResponse(
            status="ready",
            database="connected",
        )
    response.status_code = 503
    return ReadinessResponse(
        status="not_ready",
        database="disconnected",
        message="Database is not reachable. Service is not ready.",
    )


# ---------------------------------------------------------------------------
# Database (kept for backward compatibility with existing tests and integrations)
# ---------------------------------------------------------------------------

@router.get(
    "/db",
    response_model=DBHealthResponse,
    summary="Database connectivity check (compatibility endpoint)",
    description="Verifies that the backend can reach PostgreSQL. Prefer /api/health/ready for readiness probes.",
)
def health_db() -> DBHealthResponse:
    """Check database connectivity via SELECT 1."""
    connected = check_db_connection()
    if connected:
        return DBHealthResponse(status="ok", database="connected")
    return DBHealthResponse(status="degraded", database="disconnected")


# ---------------------------------------------------------------------------
# Worker Health
# ---------------------------------------------------------------------------

@router.get(
    "/worker",
    response_model=WorkerHealthResponse,
    summary="Background job worker diagnostics",
    description=(
        "Reports the runtime state of the Phase 19 in-process async worker. "
        "All counters are process-local and reset on restart. "
        "Does not expose user job details or financial data."
    ),
)
def health_worker() -> WorkerHealthResponse:
    """Return operational diagnostics for the background job worker."""
    from app.services.background_jobs import _queue

    # A task is "running" only if it exists and has not finished
    task_alive = (
        _worker_task is not None
        and not _worker_task.done()
    )

    metrics = worker_metrics.snapshot()

    return WorkerHealthResponse(
        worker_running=task_alive,
        worker_shutting_down=_worker_shutting_down,
        queue_depth=_queue.qsize(),
        jobs_completed_since_start=metrics["jobs_completed_since_start"],
        jobs_failed_since_start=metrics["jobs_failed_since_start"],
        jobs_cancelled_since_start=metrics["jobs_cancelled_since_start"],
        last_completed_at=metrics["last_completed_at"],
        last_error_at=metrics["last_error_at"],
        last_error_category=metrics["last_error_category"],
        orphans_reconciled_running_on_startup=metrics["orphans_reconciled_running_on_startup"],
        orphans_recovered_queued_on_startup=metrics["orphans_recovered_queued_on_startup"],
    )


# ---------------------------------------------------------------------------
# Scheduler Health
# ---------------------------------------------------------------------------

@router.get(
    "/scheduler",
    response_model=SchedulerHealthResponse,
    summary="Monitoring scheduler diagnostics",
    description=(
        "Reports the runtime state of the Phase 20 monitoring scheduler loop. "
        "All counters are process-local and reset on restart. "
        "Does not expose schedule details or user financial data."
    ),
)
def health_scheduler() -> SchedulerHealthResponse:
    """Return operational diagnostics for the monitoring scheduler."""
    task_alive = (
        _scheduler_task is not None
        and not _scheduler_task.done()
    )

    metrics = scheduler_metrics.snapshot()

    return SchedulerHealthResponse(
        scheduler_running=task_alive,
        scheduler_shutting_down=_scheduler_shutting_down,
        scheduler_cycles_succeeded=metrics["scheduler_cycles_succeeded"],
        scheduler_cycles_failed=metrics["scheduler_cycles_failed"],
        jobs_enqueued_by_scheduler=metrics["jobs_enqueued_by_scheduler"],
        last_poll_at=metrics["last_poll_at"],
        last_success_at=metrics["last_success_at"],
        last_error_at=metrics["last_error_at"],
        last_error_category=metrics["last_error_category"],
    )
