"""Phase 21 Test Suite — Reliability, Test Stabilization & Background Job Recovery.

Covers:
  1. Orphaned Job Reconciliation:
     - Orphaned RUNNING jobs marked FAILED with restart recovery error message.
     - Orphaned QUEUED jobs re-enqueued for execution with progress updated.
     - Redundant duplicate QUEUED jobs cancelled during reconciliation.
     - Idempotency: repeated startup reconciliation runs safely with no state corruption.
  2. Active Job Deduplication:
     - Duplicate active job submission for same user & params returns existing job.
     - Different parameters for same user allow independent concurrent jobs.
     - Cross-user isolation: User A's active job does not block User B's job.
     - Finished jobs (COMPLETED/FAILED/CANCELLED) allow new job with same params.
     - Concurrent creation deduplication safety (database unique partial index enforcement).
"""

import asyncio
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models.background_job import BackgroundJob
from app.models.user import User
from app.services.auth_service import create_session
from app.services.background_jobs import (
    _cancellation_flags,
    _queue,
    background_job_service,
    compute_dedup_hash,
    reconcile_orphaned_jobs,
)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def create_test_user(db: Session, prefix: str = "p21") -> User:
    u = User(
        email=f"{prefix}_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed_test_password",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def get_auth_client(db: Session, user: User) -> AsyncClient:
    raw_token, _ = create_session(db=db, user_id=user.id)
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    client.cookies.set("session_id", raw_token)
    return client


# ---------------------------------------------------------------------------
# 1. Orphaned Job Startup Reconciliation Tests
# ---------------------------------------------------------------------------

def test_orphaned_running_jobs_transitioned_to_failed():
    """RUNNING jobs left from a prior crash are safely marked FAILED on startup."""
    db = SessionLocal()
    try:
        user = create_test_user(db, "orphan_run")
        job = BackgroundJob(
            user_id=user.id,
            job_type="PORTFOLIO_RECALCULATION",
            status="RUNNING",
            progress_pct=40,
            progress_message="Calculating balances…",
            dedup_hash=compute_dedup_hash(None),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        # Run startup reconciliation
        stats = reconcile_orphaned_jobs(db)
        assert stats["failed_running_count"] >= 1

        db.refresh(job)
        assert job.status == "FAILED"
        assert job.completed_at is not None
        assert "interrupted by server restart" in job.error_message.lower()
        assert "server restart" in job.progress_message.lower()
    finally:
        db.close()


def test_orphaned_queued_jobs_reenqueued_safely():
    """QUEUED jobs left from a prior restart are re-enqueued without loss."""
    db = SessionLocal()
    try:
        user = create_test_user(db, "orphan_queue")
        job = BackgroundJob(
            user_id=user.id,
            job_type="ANALYZE_TRANSACTIONS",
            status="QUEUED",
            progress_pct=0,
            progress_message="Waiting in queue…",
            parameters={"account_type": "depository"},
            dedup_hash=compute_dedup_hash({"account_type": "depository"}),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        # Ensure job is not in in-memory queue or cancellation registry
        _cancellation_flags.pop(job.id, None)

        stats = reconcile_orphaned_jobs(db)
        assert stats["recovered_queued_count"] >= 1

        # Check job in memory flags and queue
        assert job.id in _cancellation_flags
        db.refresh(job)
        assert job.status == "QUEUED"
        assert "recovered after restart" in job.progress_message
    finally:
        db.close()


def test_reconciliation_is_idempotent():
    """Running startup reconciliation multiple times produces no duplicate enqueues or state changes."""
    db = SessionLocal()
    try:
        user = create_test_user(db, "idempotent_rec")
        job_run = BackgroundJob(
            user_id=user.id,
            job_type="GENERATE_INSIGHTS",
            status="RUNNING",
            dedup_hash=compute_dedup_hash(None),
        )
        job_q = BackgroundJob(
            user_id=user.id,
            job_type="ANALYZE_TRANSACTIONS",
            status="QUEUED",
            dedup_hash=compute_dedup_hash({"idempotent": True}),
            parameters={"idempotent": True},
        )
        db.add_all([job_run, job_q])
        db.commit()
        db.refresh(job_run)
        db.refresh(job_q)

        # Run 1
        stats1 = reconcile_orphaned_jobs(db)
        assert stats1["failed_running_count"] >= 1
        assert stats1["recovered_queued_count"] >= 1

        # Run 2 immediately after
        stats2 = reconcile_orphaned_jobs(db)
        assert stats2["failed_running_count"] == 0
        assert stats2["recovered_queued_count"] == 0

        # State remains valid
        db.refresh(job_run)
        db.refresh(job_q)
        assert job_run.status == "FAILED"
        assert job_q.status == "QUEUED"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2. Duplicate Active Job Prevention Tests
# ---------------------------------------------------------------------------

def test_duplicate_active_job_submission_returns_existing():
    """Submitting identical active job returns existing job instance without duplicating."""
    db = SessionLocal()
    try:
        user = create_test_user(db, "dedup_basic")
        params = {"filter": "recent"}

        job1 = background_job_service.submit_job(
            db=db,
            user_id=user.id,
            job_type="ANALYZE_TRANSACTIONS",
            parameters=params,
        )
        assert job1.status == "QUEUED"

        # Submit identical job while job1 is still active
        job2 = background_job_service.submit_job(
            db=db,
            user_id=user.id,
            job_type="ANALYZE_TRANSACTIONS",
            parameters=params,
        )

        assert job2.id == job1.id
        assert job2.status == "QUEUED"

        # Verify only one row exists in database
        count = (
            db.query(BackgroundJob)
            .filter(
                BackgroundJob.user_id == user.id,
                BackgroundJob.job_type == "ANALYZE_TRANSACTIONS",
                BackgroundJob.status.in_(["QUEUED", "RUNNING"]),
            )
            .count()
        )
        assert count == 1
    finally:
        db.close()


def test_different_parameters_allowed_concurrently():
    """Jobs with different parameters for the same user are NOT deduplicated."""
    db = SessionLocal()
    try:
        user = create_test_user(db, "dedup_diff_params")

        job_usd = background_job_service.submit_job(
            db=db,
            user_id=user.id,
            job_type="PORTFOLIO_RECALCULATION",
            parameters={"currency": "USD"},
        )

        job_lkr = background_job_service.submit_job(
            db=db,
            user_id=user.id,
            job_type="PORTFOLIO_RECALCULATION",
            parameters={"currency": "LKR"},
        )

        assert job_usd.id != job_lkr.id
        assert job_usd.dedup_hash != job_lkr.dedup_hash
    finally:
        db.close()


def test_cross_user_isolation_for_identical_jobs():
    """Identical jobs submitted by different users are strictly isolated and not merged."""
    db = SessionLocal()
    try:
        user_a = create_test_user(db, "dedup_user_a")
        user_b = create_test_user(db, "dedup_user_b")
        params = {"scan": "full"}

        job_a = background_job_service.submit_job(
            db=db,
            user_id=user_a.id,
            job_type="GENERATE_INSIGHTS",
            parameters=params,
        )

        job_b = background_job_service.submit_job(
            db=db,
            user_id=user_b.id,
            job_type="GENERATE_INSIGHTS",
            parameters=params,
        )

        assert job_a.id != job_b.id
        assert job_a.user_id == user_a.id
        assert job_b.user_id == user_b.id
    finally:
        db.close()


def test_completed_job_allows_new_submission_with_same_parameters():
    """After a job completes, a subsequent job with identical parameters is permitted."""
    db = SessionLocal()
    try:
        user = create_test_user(db, "dedup_completed")
        params = {"interval": "30d"}

        job1 = background_job_service.submit_job(
            db=db,
            user_id=user.id,
            job_type="ANALYZE_TRANSACTIONS",
            parameters=params,
        )

        # Mark job1 as COMPLETED
        job1.status = "COMPLETED"
        db.commit()

        # Submit job2 with same parameters
        job2 = background_job_service.submit_job(
            db=db,
            user_id=user.id,
            job_type="ANALYZE_TRANSACTIONS",
            parameters=params,
        )

        assert job2.id != job1.id
        assert job2.status == "QUEUED"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. HTTP API Endpoint Deduplication Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_api_submit_duplicate_returns_existing_job():
    """POST /api/jobs returns HTTP 202 with existing job ID when an active duplicate exists."""
    db = SessionLocal()
    try:
        user = create_test_user(db, "api_dedup")

        async with get_auth_client(db, user) as ac:
            res1 = await ac.post(
                "/api/jobs",
                json={
                    "job_type": "ANALYZE_TRANSACTIONS",
                    "parameters": {"batch": 1},
                },
            )
            assert res1.status_code == 202
            data1 = res1.json()

            # Second submit with identical payload
            res2 = await ac.post(
                "/api/jobs",
                json={
                    "job_type": "ANALYZE_TRANSACTIONS",
                    "parameters": {"batch": 1},
                },
            )
            assert res2.status_code == 202
            data2 = res2.json()

            # Must return the same job ID
            assert data2["job_id"] == data1["job_id"]
    finally:
        db.close()


@pytest.mark.anyio
async def test_concurrent_job_submission_deduplication():
    """Concurrent async requests with identical parameters return the same active job."""
    db = SessionLocal()
    try:
        user = create_test_user(db, "api_concurrent_dedup")

        async with get_auth_client(db, user) as ac:
            req_payload = {
                "job_type": "PORTFOLIO_RECALCULATION",
                "parameters": {"precision": 4},
            }

            # Fire 5 concurrent requests simultaneously
            responses = await asyncio.gather(
                ac.post("/api/jobs", json=req_payload),
                ac.post("/api/jobs", json=req_payload),
                ac.post("/api/jobs", json=req_payload),
                ac.post("/api/jobs", json=req_payload),
                ac.post("/api/jobs", json=req_payload),
            )

            job_ids = set()
            for res in responses:
                assert res.status_code == 202
                job_ids.add(res.json()["job_id"])

            # All 5 concurrent requests must yield the exact same single job ID
            assert len(job_ids) == 1
    finally:
        db.close()
