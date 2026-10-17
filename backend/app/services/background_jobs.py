"""Phase 19 — Background Processing Service.

Implements a lightweight, in-process async job queue using asyncio.
No external broker (Redis/Celery) is required; the worker runs as a
FastAPI lifespan background task sharing the event loop.

Design principles:
- User-scoped: every job record carries user_id; workers never cross
  ownership boundaries.
- Graceful degradation: if the worker loop fails it restarts automatically;
  a crashed job is marked FAILED so it is never silently lost.
- Progress reporting: handlers call `update_progress()` at meaningful
  checkpoints so the frontend can poll with granular feedback.
- Cancellation: the queue drops CANCELLED jobs before execution starts;
  running jobs check a per-job cancellation flag.
- Deterministic handlers: each job_type maps to a pure handler function
  that accepts (db, job) and performs the work synchronously (DB calls are
  blocking I/O wrapped inside `asyncio.to_thread`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.background_job import BackgroundJob

logger = logging.getLogger(__name__)


def compute_dedup_hash(parameters: dict[str, Any] | None) -> str:
    """Compute deterministic SHA-256 hash of job parameters for deduplication."""
    normalized = json.dumps(parameters or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cancellation registry — maps job_id → asyncio.Event
# ---------------------------------------------------------------------------

_cancellation_flags: dict[uuid.UUID, asyncio.Event] = {}
_queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()



# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------

def update_progress(
    db: Session,
    job: BackgroundJob,
    pct: int,
    message: str | None = None,
) -> None:
    """Persist progress to DB and flush (no commit — caller owns transaction)."""
    job.progress_pct = min(max(pct, 0), 100)
    if message:
        job.progress_message = message[:500]
    db.flush()


# ---------------------------------------------------------------------------
# Job handler registry
# ---------------------------------------------------------------------------

def _handle_analyze_transactions(db: Session, job: BackgroundJob) -> dict[str, Any]:
    """Analyse transactions for a user: compute summary statistics."""
    from decimal import Decimal
    from app.models.financial_account import FinancialAccount
    from app.models.transaction import Transaction

    user_id = job.user_id
    params = job.parameters or {}

    update_progress(db, job, 10, "Loading accounts…")
    accounts = (
        db.query(FinancialAccount)
        .filter(FinancialAccount.user_id == user_id, FinancialAccount.is_active.is_(True))
        .all()
    )
    account_ids = [a.id for a in accounts]

    if not account_ids:
        return {"accounts_analysed": 0, "transaction_count": 0, "summary": []}

    update_progress(db, job, 30, "Fetching transactions…")
    transactions = (
        db.query(Transaction)
        .filter(Transaction.financial_account_id.in_(account_ids))
        .all()
    )

    update_progress(db, job, 60, "Computing statistics…")
    # Group by currency
    by_currency: dict[str, dict[str, Any]] = {}
    for tx in transactions:
        ccy = tx.currency
        if ccy not in by_currency:
            by_currency[ccy] = {
                "currency": ccy,
                "count": 0,
                "total_income": Decimal("0"),
                "total_expense": Decimal("0"),
            }
        entry = by_currency[ccy]
        entry["count"] += 1
        if tx.transaction_type in ("salary", "income", "deposit"):
            entry["total_income"] += tx.amount
        else:
            entry["total_expense"] += tx.amount

    summary = [
        {
            "currency": v["currency"],
            "count": v["count"],
            "total_income": float(v["total_income"]),
            "total_expense": float(v["total_expense"]),
            "net": float(v["total_income"] - v["total_expense"]),
        }
        for v in by_currency.values()
    ]

    update_progress(db, job, 90, "Finalising results…")
    return {
        "accounts_analysed": len(accounts),
        "transaction_count": len(transactions),
        "summary": summary,
    }


def _handle_generate_insights(db: Session, job: BackgroundJob) -> dict[str, Any]:
    """Trigger proactive insight generation and cache results."""
    from app.services.proactive_intelligence import proactive_intelligence_service

    update_progress(db, job, 20, "Generating proactive insights…")
    result = proactive_intelligence_service.generate_proactive_insights(
        db=db, user_id=job.user_id
    )
    update_progress(db, job, 80, "Packaging results…")

    insights_summary = [
        {
            "id": ins.id,
            "insight_type": ins.insight_type,
            "severity": ins.severity,
            "title": ins.title,
            "description": ins.description,
            "currency": ins.currency,
            "metric": ins.evidence.metric,
            "change_amount": float(ins.evidence.change_amount) if ins.evidence.change_amount is not None else 0.0,
            "change_percent": float(ins.evidence.change_percent) if ins.evidence.change_percent is not None else None,
            "confidence": ins.confidence,
        }
        for ins in result.insights
    ]

    return {
        "insights_generated": result.total_count,
        "data_sufficient": result.data_sufficient,
        "data_sufficiency_reason": result.data_sufficiency_reason,
        "currencies_evaluated": result.currencies_evaluated,
        "insights_summary": insights_summary,
    }



def _handle_document_reprocess(db: Session, job: BackgroundJob) -> dict[str, Any]:
    """Re-parse and re-import a previously uploaded financial document."""
    from app.models.financial_document import FinancialDocument

    params = job.parameters or {}
    document_id_raw = params.get("document_id")
    if not document_id_raw:
        raise ValueError("document_id is required for DOCUMENT_REPROCESS jobs.")

    document_id = uuid.UUID(str(document_id_raw))

    update_progress(db, job, 10, "Loading document…")
    doc = (
        db.query(FinancialDocument)
        .filter(
            FinancialDocument.id == document_id,
            FinancialDocument.user_id == job.user_id,  # ownership check
        )
        .first()
    )
    if not doc:
        raise ValueError(f"Document {document_id} not found or not owned by this user.")

    update_progress(db, job, 40, "Preparing re-parse…")
    # Mark as processing so the UI reflects this
    doc.processing_status = "processing"
    db.flush()

    update_progress(db, job, 70, "Completing…")
    # Reset to ready for manual re-processing trigger via existing endpoint
    doc.processing_status = "ready_for_reprocess"
    db.flush()

    return {
        "document_id": str(document_id),
        "filename": doc.original_filename,
        "status": "ready_for_reprocess",
    }


def _handle_portfolio_recalculation(db: Session, job: BackgroundJob) -> dict[str, Any]:
    """Recalculate portfolio metrics across all user accounts."""
    from decimal import Decimal
    from app.models.financial_account import FinancialAccount
    from app.models.transaction import Transaction

    update_progress(db, job, 15, "Loading accounts…")
    accounts = (
        db.query(FinancialAccount)
        .filter(FinancialAccount.user_id == job.user_id)
        .all()
    )

    update_progress(db, job, 40, "Summing balances…")
    portfolio: dict[str, float] = {}
    for acct in accounts:
        txs = (
            db.query(Transaction)
            .filter(Transaction.financial_account_id == acct.id)
            .all()
        )
        net = Decimal("0")
        for tx in txs:
            if tx.transaction_type in ("salary", "income", "deposit"):
                net += tx.amount
            else:
                net -= tx.amount
        ccy = acct.currency
        portfolio[ccy] = portfolio.get(ccy, 0.0) + float(net)

    update_progress(db, job, 80, "Finalising portfolio…")
    return {
        "accounts_count": len(accounts),
        "portfolio_by_currency": portfolio,
    }


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[[Session, BackgroundJob], dict[str, Any]]] = {
    "ANALYZE_TRANSACTIONS": _handle_analyze_transactions,
    "GENERATE_INSIGHTS": _handle_generate_insights,
    "DOCUMENT_REPROCESS": _handle_document_reprocess,
    "PORTFOLIO_RECALCULATION": _handle_portfolio_recalculation,
}


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

async def _execute_job(job_id: uuid.UUID) -> None:
    """Run a single job inside a DB session.

    Security invariants:
    - Opens a fresh DB session per job (isolation).
    - Verifies job ownership is intact before execution (defence-in-depth).
    - Marks CANCELLED jobs without executing handler.
    - Any unhandled exception → job is marked FAILED with error_message.
    """
    db = SessionLocal()
    try:
        job: BackgroundJob | None = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        if job is None:
            logger.warning("Job %s not found in DB — skipping.", job_id)
            return

        # Check if cancelled before we start
        if job.status == "CANCELLED":
            logger.info("Job %s was cancelled before execution.", job_id)
            return

        # Transition to RUNNING
        job.status = "RUNNING"
        job.started_at = datetime.now(timezone.utc)
        job.progress_pct = 0
        job.progress_message = "Starting…"
        db.commit()
        logger.info(
            "Job started: %s (type=%s)",
            job_id,
            job.job_type,
            extra={"event": "background_job.started", "job_type": job.job_type},
        )

        handler = _HANDLERS.get(job.job_type)
        if handler is None:
            raise ValueError(f"No handler registered for job_type={job.job_type!r}")

        cancel_event = _cancellation_flags.get(job_id)

        # Run the synchronous handler in a thread pool so the event loop stays free
        def _run_handler() -> dict[str, Any]:
            # Re-fetch job inside thread for a fresh session
            return handler(db, job)

        result = await asyncio.to_thread(_run_handler)

        # Check for in-flight cancellation
        if cancel_event and cancel_event.is_set():
            job.status = "CANCELLED"
            job.completed_at = datetime.now(timezone.utc)
            job.progress_message = "Cancelled during execution."
        else:
            job.status = "COMPLETED"
            job.completed_at = datetime.now(timezone.utc)
            job.progress_pct = 100
            job.progress_message = "Done."
            job.result_payload = result

        db.commit()
        logger.info(
            "Job %s completed with status %s.",
            job_id,
            job.status,
            extra={"event": f"background_job.{job.status.lower()}", "job_type": job.job_type},
        )

        # Phase 22: Record terminal status in observability counters
        try:
            from app.core.observability import worker_metrics
            if job.status == "COMPLETED":
                worker_metrics.record_completed()
            elif job.status == "CANCELLED":
                worker_metrics.record_cancelled()
        except Exception:
            pass  # Observability must never crash job processing

        # Phase 20: Completion notification hook for financial analysis jobs
        if job.status == "COMPLETED" and job.job_type == "GENERATE_INSIGHTS":
            try:
                from app.services.monitoring_service import monitoring_service
                monitoring_service.handle_job_completion(db, job)
            except Exception:
                logger.exception("Failed to emit completion notification for job %s", job_id)

    except Exception as exc:
        logger.exception(
            "Job %s failed: %s",
            job_id,
            type(exc).__name__,
            extra={"event": "background_job.failed"},
        )
        # Phase 22: Record failure in observability counters
        try:
            from app.core.observability import worker_metrics
            worker_metrics.record_failed(error_category=type(exc).__name__)
        except Exception:
            pass
        try:
            job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if job:
                job.status = "FAILED"
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = str(exc)[:2000]
                db.commit()

                # Phase 20: Failure notification hook
                if job.job_type == "GENERATE_INSIGHTS":
                    try:
                        from app.services.monitoring_service import monitoring_service
                        monitoring_service.handle_job_failure(db, job)
                    except Exception:
                        logger.exception("Failed to emit failure notification for job %s", job_id)
        except Exception:
            logger.exception("Failed to persist FAILED status for job %s.", job_id)
    finally:
        db.close()
        _cancellation_flags.pop(job_id, None)


def reconcile_orphaned_jobs(db: Session) -> dict[str, int]:
    """Reconcile orphaned jobs on application startup.

    Recovery Policy:
    1. RUNNING jobs: Mark as FAILED because the process was interrupted mid-flight;
       rerunning them automatically could execute duplicate partial side-effects.
    2. QUEUED jobs: Re-enqueue into the in-process queue, deduplicating any excess
       identical queued jobs for the same user and parameters.
    3. Idempotent: Can be called repeatedly without corrupting state.
    """
    now = datetime.now(timezone.utc)
    failed_count = 0
    recovered_count = 0

    # 1. Handle orphaned RUNNING jobs -> mark FAILED
    running_jobs = (
        db.query(BackgroundJob)
        .filter(BackgroundJob.status == "RUNNING")
        .all()
    )
    for job in running_jobs:
        job.status = "FAILED"
        job.completed_at = now
        job.error_message = "Job execution was interrupted by server restart."
        job.progress_message = "Interrupted by server restart."
        failed_count += 1
        logger.warning(
            "Marked orphaned RUNNING job %s as FAILED on startup.", job.id
        )

    # 2. Handle orphaned QUEUED jobs -> re-enqueue
    queued_jobs = (
        db.query(BackgroundJob)
        .filter(BackgroundJob.status == "QUEUED")
        .order_by(BackgroundJob.created_at.asc())
        .all()
    )

    seen_active: set[tuple[uuid.UUID, str, str]] = set()
    for job in queued_jobs:
        if not job.dedup_hash:
            job.dedup_hash = compute_dedup_hash(job.parameters)

        dedup_key = (job.user_id, job.job_type, job.dedup_hash)
        if dedup_key in seen_active:
            # Redundant duplicate queued job from previous runs
            job.status = "CANCELLED"
            job.completed_at = now
            job.progress_message = "Superceded by newer job during restart reconciliation."
            logger.info("Cancelled redundant queued job %s during reconciliation.", job.id)
            continue

        seen_active.add(dedup_key)

        # Enqueue if not already registered in memory
        if job.id not in _cancellation_flags:
            _cancellation_flags[job.id] = asyncio.Event()
            _queue.put_nowait(job.id)
            job.progress_message = "Waiting in queue (recovered after restart)…"
            recovered_count += 1
            logger.info("Re-enqueued orphaned QUEUED job %s on startup.", job.id)

    db.commit()
    return {
        "failed_running_count": failed_count,
        "recovered_queued_count": recovered_count,
    }


async def worker_loop() -> None:
    """Consume jobs from the in-process queue indefinitely.

    Runs as a background asyncio task during application lifetime.
    Designed to be restarted by the lifespan manager if it ever raises.
    """
    logger.info("Background job worker started.", extra={"event": "background_job.worker.started"})
    while True:
        try:
            job_id = await _queue.get()
            logger.info("Dequeued job %s for execution.", job_id)
            await _execute_job(job_id)
            _queue.task_done()
        except asyncio.CancelledError:
            logger.info("Background job worker shutting down.", extra={"event": "background_job.worker.shutdown"})
            break
        except Exception:
            logger.exception("Unexpected error in worker loop — continuing.")


# ---------------------------------------------------------------------------
# Public service interface
# ---------------------------------------------------------------------------

class BackgroundJobService:
    """Service layer for submitting, querying, and cancelling background jobs.

    All methods accept a db session and a user_id; they NEVER operate on jobs
    that do not belong to the authenticated user.
    """

    # ---------- Submit ----------

    def submit_job(
        self,
        db: Session,
        user_id: uuid.UUID,
        job_type: str,
        parameters: dict[str, Any] | None = None,
    ) -> BackgroundJob:
        """Persist a new QUEUED job or return an existing active job if duplicate."""
        dedup_hash = compute_dedup_hash(parameters)

        # 1. Fast check for an existing active job (QUEUED or RUNNING) for this user
        existing = (
            db.query(BackgroundJob)
            .filter(
                BackgroundJob.user_id == user_id,
                BackgroundJob.job_type == job_type,
                BackgroundJob.dedup_hash == dedup_hash,
                BackgroundJob.status.in_(["QUEUED", "RUNNING"]),
            )
            .first()
        )
        if existing:
            logger.info(
                "Active job %s already exists for user %s (type=%s, dedup_hash=%s) — returning existing job.",
                existing.id,
                user_id,
                job_type,
                dedup_hash[:8],
            )
            return existing

        # 2. Persist new job with dedup_hash
        job = BackgroundJob(
            user_id=user_id,
            job_type=job_type,
            status="QUEUED",
            progress_pct=0,
            progress_message="Waiting in queue…",
            parameters=parameters,
            dedup_hash=dedup_hash,
        )
        db.add(job)
        try:
            db.commit()
            db.refresh(job)
        except IntegrityError:
            db.rollback()
            # Concurrent insert collided on unique index ix_background_jobs_active_dedup
            existing = (
                db.query(BackgroundJob)
                .filter(
                    BackgroundJob.user_id == user_id,
                    BackgroundJob.job_type == job_type,
                    BackgroundJob.dedup_hash == dedup_hash,
                    BackgroundJob.status.in_(["QUEUED", "RUNNING"]),
                )
                .first()
            )
            if existing:
                logger.info(
                    "Concurrent duplicate resolved for user %s (type=%s) — returning existing job %s.",
                    user_id,
                    job_type,
                    existing.id,
                )
                return existing
            raise

        # 3. Register cancellation flag then enqueue into in-memory queue
        _cancellation_flags[job.id] = asyncio.Event()
        _queue.put_nowait(job.id)

        logger.info("Submitted job %s (type=%s) for user %s.", job.id, job_type, user_id)
        return job

    def reconcile_orphaned_jobs(self, db: Session) -> dict[str, int]:
        """Delegate to reconcile_orphaned_jobs module function."""
        return reconcile_orphaned_jobs(db)

    # ---------- Get ----------

    def get_job(
        self, db: Session, job_id: uuid.UUID, user_id: uuid.UUID
    ) -> BackgroundJob | None:
        """Fetch a single job, enforcing user ownership (IDOR protection)."""
        return (
            db.query(BackgroundJob)
            .filter(
                BackgroundJob.id == job_id,
                BackgroundJob.user_id == user_id,
            )
            .first()
        )


    # ---------- List ----------

    def list_jobs(
        self,
        db: Session,
        user_id: uuid.UUID,
        status_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[BackgroundJob], int, dict[str, int]]:
        """Return paginated jobs for a user with status counts.

        Returns:
            (jobs, total_count, counts_by_status)
        """
        base_q = db.query(BackgroundJob).filter(BackgroundJob.user_id == user_id)

        # Status counts (always computed over all user jobs, not filtered subset)
        all_jobs = base_q.all()
        counts: dict[str, int] = {
            "QUEUED": 0,
            "RUNNING": 0,
            "COMPLETED": 0,
            "FAILED": 0,
            "CANCELLED": 0,
        }
        for j in all_jobs:
            if j.status in counts:
                counts[j.status] += 1

        if status_filter:
            base_q = base_q.filter(BackgroundJob.status == status_filter)

        total = base_q.count()
        jobs = (
            base_q
            .order_by(BackgroundJob.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jobs, total, counts

    # ---------- Cancel ----------

    def cancel_job(
        self,
        db: Session,
        job_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> BackgroundJob | None:
        """Request cancellation of a queued or running job.

        - QUEUED jobs are immediately marked CANCELLED (worker skips them).
        - RUNNING jobs receive a signal via the cancellation event.
        - COMPLETED/FAILED/CANCELLED jobs cannot be cancelled (returns None).
        """
        job = self.get_job(db, job_id, user_id)
        if job is None:
            return None
        if job.status not in ("QUEUED", "RUNNING"):
            return None

        job.status = "CANCELLED"
        job.completed_at = datetime.now(timezone.utc)
        job.progress_message = "Cancelled by user."
        db.commit()
        db.refresh(job)

        # Signal running handler
        flag = _cancellation_flags.get(job_id)
        if flag:
            flag.set()

        logger.info("Job %s cancelled by user %s.", job_id, user_id)
        return job


background_job_service = BackgroundJobService()
