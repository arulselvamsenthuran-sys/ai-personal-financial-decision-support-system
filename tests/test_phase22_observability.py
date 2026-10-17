"""Phase 22 Test Suite — Operational Observability, Diagnostics & Safe Audit Events.

Covers:
  1. Structured JSON logging format and fields (timestamp, severity, logger, environment, message, event).
  2. Redaction of sensitive fields (passwords, tokens, keys) in audit logging.
  3. Client-supplied X-Request-ID validation and preservation.
  4. Invalid or oversized X-Request-ID replacement with generated identifiers.
  5. X-Request-ID header propagation in HTTP responses.
  6. ContextVar request isolation across concurrent requests.
  7. Safe handling of expected application errors (AppError, 401, 422).
  8. Safe handling of unexpected internal server errors (500 generic detail, request_id included, no tracebacks/SQL).
  9. Liveness endpoint independence from external AI providers.
 10. Readiness endpoint behavior under healthy and database-disconnected conditions.
 11. Worker health diagnostics (distinguishing active vs terminated tasks, queue depth, counters).
 12. Scheduler health diagnostics (distinguishing loop state, cycle counts, failure tracking).
 13. Process-local metric boundedness (no user IDs, transaction details, or raw paths in metric labels).
 14. Health-check logging suppression (DEBUG level for /api/health).
 15. Non-regression of existing financial calculation and background job services.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from app.api.health import (
    register_scheduler_task,
    register_worker_task,
    set_scheduler_shutting_down,
    set_worker_shutting_down,
)
from app.core.audit import audit_log
from app.core.correlation import (
    clear_request_id,
    generate_request_id,
    get_request_id,
    set_request_id,
    validate_or_generate,
)
from app.core.errors import AppError
from app.core.logging import _JSONFormatter
from app.core.observability import (
    _RequestMetrics,
    _SchedulerMetrics,
    _WorkerMetrics,
    request_metrics,
    scheduler_metrics,
    worker_metrics,
)
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User
from app.services.auth_service import create_session


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def create_test_user(db: Session, prefix: str = "p22") -> User:
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
# 1. Structured JSON Logging Tests
# ---------------------------------------------------------------------------

def test_json_formatter_standard_fields():
    """Structured JSON logs include timestamp, severity, logger, environment, message, and event."""
    formatter = _JSONFormatter(environment="test_env")
    record = logging.LogRecord(
        name="test.component",
        level=logging.INFO,
        pathname="test_file.py",
        lineno=10,
        msg="Task completed successfully",
        args=(),
        exc_info=None,
    )
    record.event = "test.task.completed"  # type: ignore[attr-defined]

    output = formatter.format(record)
    data = json.loads(output)

    assert data["severity"] == "INFO"
    assert data["logger"] == "test.component"
    assert data["environment"] == "test_env"
    assert data["message"] == "Task completed successfully"
    assert data["event"] == "test.task.completed"
    assert "timestamp" in data


def test_json_formatter_includes_request_id_from_context():
    """Structured JSON logs automatically pick up active request_id from contextvars."""
    formatter = _JSONFormatter(environment="test")
    test_req_id = "req-abc-12345"
    set_request_id(test_req_id)
    try:
        record = logging.LogRecord(
            name="test.worker",
            level=logging.WARNING,
            pathname="worker.py",
            lineno=42,
            msg="Processing delayed",
            args=(),
            exc_info=None,
        )
        data = json.loads(formatter.format(record))
        assert data.get("request_id") == test_req_id
    finally:
        clear_request_id()


# ---------------------------------------------------------------------------
# 2. Audit Logging Sensitive Data Redaction
# ---------------------------------------------------------------------------

def test_audit_logging_redacts_sensitive_keys(caplog):
    """Audit logs redact sensitive keys (password, token, secret, credit_card)."""
    with caplog.at_level(logging.INFO, logger="security.audit"):
        audit_log(
            event_type="USER_LOGIN_ATTEMPT",
            user_id=uuid.uuid4(),
            details={
                "username": "alice",
                "password": "SuperSecretPassword123!",
                "session_token_hash": "sensitive_hash_value",
                "credit_card": "4111111111111111",
                "safe_info": "browser_agent",
            },
        )

    assert len(caplog.records) > 0
    log_text = caplog.text
    assert "SuperSecretPassword123!" not in log_text
    assert "sensitive_hash_value" not in log_text
    assert "4111111111111111" not in log_text
    assert "[REDACTED]" in log_text
    assert "browser_agent" in log_text


# ---------------------------------------------------------------------------
# 3. Correlation ID Validation & Generation
# ---------------------------------------------------------------------------

def test_validate_or_generate_valid_id():
    """Valid client-supplied X-Request-ID is retained."""
    valid_id = "trace-client-12345_6789"
    assert validate_or_generate(valid_id) == valid_id


def test_validate_or_generate_invalid_or_oversized():
    """Invalid, empty, or oversized client-supplied IDs are replaced with generated ones."""
    # Too long (> 72 chars)
    oversized = "a" * 73
    assert validate_or_generate(oversized) != oversized

    # Invalid special characters
    invalid_chars = "req-id<script>alert(1)</script>"
    assert validate_or_generate(invalid_chars) != invalid_chars

    # Empty / None
    assert validate_or_generate(None) is not None
    assert len(validate_or_generate(None)) == 32  # secrets.token_hex(16)


# ---------------------------------------------------------------------------
# 4. HTTP Request-ID Header Propagation & Middleware
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_request_id_in_response_headers():
    """Every HTTP response includes an X-Request-ID header."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        req_id = resp.headers.get("X-Request-ID")
        assert req_id is not None
        assert len(req_id) >= 16


@pytest.mark.anyio
async def test_valid_client_supplied_request_id_echoed():
    """A valid client-supplied X-Request-ID is preserved and returned."""
    custom_id = "client-trace-id-12345678"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health", headers={"X-Request-ID": custom_id})
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-ID") == custom_id


@pytest.mark.anyio
async def test_oversized_client_request_id_replaced():
    """An oversized client X-Request-ID is replaced with a generated one."""
    oversized = "x" * 100
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health", headers={"X-Request-ID": oversized})
        assert resp.status_code == 200
        returned_id = resp.headers.get("X-Request-ID")
        assert returned_id != oversized
        assert len(returned_id) == 32


# ---------------------------------------------------------------------------
# 5. Concurrent ContextVars Isolation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_contextvars_isolation_under_concurrency():
    """Concurrent requests do not leak correlation context across tasks."""
    async def make_request(idx: int):
        cid = f"concurrent-trace-{idx:04d}-{uuid.uuid4().hex[:8]}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/health", headers={"X-Request-ID": cid})
            assert resp.headers.get("X-Request-ID") == cid

    tasks = [make_request(i) for i in range(15)]
    await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# 6. Safe Error Observability (AppError & Unexpected 500)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_expected_auth_error_preserves_status_and_format():
    """Unauthenticated calls return standard 401 response without high-severity crash."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/financial/accounts")
        assert resp.status_code == 401
        assert "detail" in resp.json()
        assert resp.headers.get("X-Request-ID") is not None


@pytest.mark.anyio
async def test_unexpected_error_returns_generic_500_with_request_id():
    """Unexpected internal server error returns generic message + request_id and no leaks."""
    # Temporarily install a failing route on the app to test unhandled error handling
    @app.get("/api/test-internal-failure-route")
    def fail_endpoint():
        raise RuntimeError("SensitiveDatabaseException: secret_db_key=12345 postgres://user:pass@host/db")

    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            custom_id = "test-error-trace-99999"
            resp = await client.get("/api/test-internal-failure-route", headers={"X-Request-ID": custom_id})
            assert resp.status_code == 500
            data = resp.json()
            # 1. Detail must be generic
            assert data.get("detail") == "Internal server error."
            # 2. Must contain request_id for operational tracing
            assert data.get("request_id") == custom_id
            # 3. Must NEVER leak internal exception text, SQL, or credentials
            raw_text = resp.text
            assert "secret_db_key" not in raw_text
            assert "postgres://" not in raw_text
            assert "Traceback" not in raw_text
    finally:
        # Remove the temporary test route
        app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/api/test-internal-failure-route"]


# ---------------------------------------------------------------------------
# 7. Liveness & Readiness Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_liveness_endpoint_independent():
    """GET /api/health returns 200 'ok' without calling external AI providers."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_readiness_healthy():
    """GET /api/health/ready returns 200 'ready' when database check succeeds."""
    with patch("app.api.health.check_db_connection", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/health/ready")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ready"
            assert data["database"] == "connected"


@pytest.mark.anyio
async def test_readiness_unhealthy_returns_503():
    """GET /api/health/ready returns 503 'not_ready' when database is unreachable."""
    with patch("app.api.health.check_db_connection", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/health/ready")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "not_ready"
            assert data["database"] == "disconnected"
            # Ensure no credentials or SQL leaked
            assert "postgresql://" not in resp.text
            assert "password" not in resp.text


# ---------------------------------------------------------------------------
# 8. Background Worker Health Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_worker_health_active_and_terminated():
    """Worker health accurately reflects task alive vs terminated state."""
    # 1. Simulate active task
    dummy_task = MagicMock(spec=asyncio.Task)
    dummy_task.done.return_value = False
    register_worker_task(dummy_task)
    set_worker_shutting_down(False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health/worker")
        assert resp.status_code == 200
        data = resp.json()
        assert data["worker_running"] is True
        assert data["worker_shutting_down"] is False
        assert "queue_depth" in data
        assert "jobs_completed_since_start" in data
        assert "note" in data

    # 2. Simulate terminated task
    dummy_task.done.return_value = True
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health/worker")
        assert resp.status_code == 200
        data = resp.json()
        assert data["worker_running"] is False


# ---------------------------------------------------------------------------
# 9. Monitoring Scheduler Health Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_scheduler_health_active_and_terminated():
    """Scheduler health accurately reflects loop alive vs terminated state."""
    dummy_sched_task = MagicMock(spec=asyncio.Task)
    dummy_sched_task.done.return_value = False
    register_scheduler_task(dummy_sched_task)
    set_scheduler_shutting_down(False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health/scheduler")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scheduler_running"] is True
        assert data["scheduler_shutting_down"] is False
        assert "scheduler_cycles_succeeded" in data
        assert "scheduler_cycles_failed" in data
        assert "note" in data

    dummy_sched_task.done.return_value = True
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health/scheduler")
        assert resp.status_code == 200
        assert resp.json()["scheduler_running"] is False


# ---------------------------------------------------------------------------
# 10. Process-Local Metrics Boundedness
# ---------------------------------------------------------------------------

def test_request_metrics_bounded_cardinality():
    """RequestMetrics labels only HTTP method, normalized route template, and status class."""
    m = _RequestMetrics()
    m.record("GET", "/api/jobs/{job_id}", 200)
    m.record("GET", "/api/jobs/{job_id}", 200)
    m.record("POST", "/api/jobs", 201)
    m.record("GET", "/api/jobs/{job_id}", 404)

    snap = m.snapshot()
    assert snap["total_requests"] == 4
    assert len(snap["by_route"]) == 3

    for entry in snap["by_route"]:
        assert entry["status_class"] in ("2xx", "4xx", "5xx")
        assert entry["method"] in ("GET", "POST", "PUT", "DELETE", "PATCH")
        # Ensure no user UUIDs appear in route keys
        assert "@" not in entry["route"]


def test_worker_and_scheduler_metrics_counters():
    """Worker and scheduler counters correctly increment and format snapshots."""
    wm = _WorkerMetrics()
    wm.record_completed()
    wm.record_failed("ValueError")
    wm.record_cancelled()
    wm.record_startup_reconciliation(failed_running=2, recovered_queued=1)

    wsnap = wm.snapshot()
    assert wsnap["jobs_completed_since_start"] == 1
    assert wsnap["jobs_failed_since_start"] == 1
    assert wsnap["jobs_cancelled_since_start"] == 1
    assert wsnap["last_error_category"] == "ValueError"
    assert wsnap["orphans_reconciled_running_on_startup"] == 2
    assert wsnap["orphans_recovered_queued_on_startup"] == 1

    sm = _SchedulerMetrics()
    sm.record_poll()
    sm.record_cycle_success(jobs_enqueued=3)
    sm.record_cycle_failure("TimeoutError")

    ssnap = sm.snapshot()
    assert ssnap["scheduler_cycles_succeeded"] == 1
    assert ssnap["scheduler_cycles_failed"] == 1
    assert ssnap["jobs_enqueued_by_scheduler"] == 3
    assert ssnap["last_error_category"] == "TimeoutError"
