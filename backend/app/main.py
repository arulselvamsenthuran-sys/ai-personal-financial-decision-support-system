"""FastAPI application entry point — Phase 22 observability additions.

Changes from Phase 21:
- JSON structured logging with configurable level and environment.
- CorrelationMiddleware: attaches X-Request-ID to every request and response.
- Structured application.startup and application.shutdown events.
- Worker and scheduler asyncio tasks registered with health endpoints.
- Observability metrics updated from startup reconciliation results.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.background_jobs import router as background_jobs_router  # Phase 19
from app.api.conversations import router as conversations_router  # Phase 17
from app.api.financial import router as financial_router
from app.api.health import (
    router as health_router,
    register_worker_task,
    register_scheduler_task,
    set_worker_shutting_down,
    set_scheduler_shutting_down,
)
from app.api.monitoring import router as monitoring_router  # Phase 20
from app.api.oauth import router as oauth_router
from app.api.proactive import router as proactive_router  # Phase 18
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import CorrelationMiddleware
from app.core.observability import worker_metrics
from app.services.background_jobs import worker_loop  # Phase 19
from app.services.monitoring_service import scheduler_loop  # Phase 20

setup_logging(environment=settings.environment, log_level=settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — runs on startup and shutdown."""
    logger.info(
        "Application starting",
        extra={
            "event": "application.startup",
            "app_name": settings.app_name,
            "environment": settings.environment,
        },
    )

    # Phase 21: Reconcile orphaned background jobs from prior process crash/restart
    reconciliation_stats = {"failed_running_count": 0, "recovered_queued_count": 0}
    try:
        from app.db.session import SessionLocal
        from app.services.background_jobs import reconcile_orphaned_jobs
        with SessionLocal() as db:
            reconciliation_stats = reconcile_orphaned_jobs(db)
            logger.info(
                "Startup background job reconciliation completed",
                extra={
                    "event": "application.startup",
                    "reconciliation": reconciliation_stats,
                },
            )
    except Exception as exc:
        logger.exception(
            "Failed during startup background job reconciliation",
            extra={"event": "application.startup", "error_type": type(exc).__name__},
        )

    # Phase 22: Persist reconciliation stats into worker metrics
    worker_metrics.record_startup_reconciliation(
        failed_running=reconciliation_stats.get("failed_running_count", 0),
        recovered_queued=reconciliation_stats.get("recovered_queued_count", 0),
    )

    # Phase 19: Start the background job worker
    worker_task = asyncio.create_task(worker_loop())
    register_worker_task(worker_task)
    logger.info("Background job worker task started.", extra={"event": "application.startup"})

    # Phase 20: Start the recurring monitoring scheduler
    scheduler_task = asyncio.create_task(scheduler_loop())
    register_scheduler_task(scheduler_task)
    logger.info("Monitoring scheduler task started.", extra={"event": "application.startup"})

    yield

    # Gracefully cancel background tasks on shutdown
    set_worker_shutting_down(True)
    set_scheduler_shutting_down(True)
    worker_task.cancel()
    scheduler_task.cancel()
    try:
        await asyncio.gather(worker_task, scheduler_task, return_exceptions=True)
    except Exception:
        pass

    logger.info(
        "Application shutting down",
        extra={"event": "application.shutdown", "app_name": settings.app_name},
    )


app = FastAPI(
    title=settings.app_name,
    description="AI-Powered Personal Financial Decision Support System — Phase 22 Observability",
    version="0.22.0",
    lifespan=lifespan,
    swagger_ui_parameters={"withCredentials": True},
)

# ---- CORS ----
# Note: allow_origins must be explicit (never ["*"]) when allow_credentials=True
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ---- Phase 22: Correlation ID + request logging middleware ----
app.add_middleware(CorrelationMiddleware)

# ---- Error handlers ----
register_exception_handlers(app)

# ---- Routers ----
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(oauth_router)
app.include_router(financial_router)
app.include_router(conversations_router)  # Phase 17
app.include_router(proactive_router)      # Phase 18
app.include_router(background_jobs_router)  # Phase 19
app.include_router(monitoring_router)     # Phase 20
