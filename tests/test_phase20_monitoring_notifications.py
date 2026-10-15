"""Phase 20 Test Suite — Scheduled Monitoring and In-App Notifications.

Covers:
  1. Due-Time Calculation:
     - Daily schedule: same day if before hour, next day if after.
     - Weekly schedule: calculates correct future weekday.
     - Handles timezone awareness strictly in UTC.
  2. Schedule CRUD & API Security:
     - Unauthenticated access to /api/monitoring/schedules returns 401.
     - User can create daily and weekly schedules (returns 201).
     - Validation: WEEKLY requires day_of_week (1-7).
     - User can list their own schedules.
     - User can update schedule and next_run_at is recalculated.
     - User can toggle schedule (enabling calculates next_run_at; disabling clears it).
     - User can delete schedule safely.
     - IDOR Protection: User B cannot view, update, toggle, delete, or trigger User A's schedule (returns 404).
  3. Manual Execution Trigger:
     - POST /api/monitoring/schedules/{id}/trigger runs schedule immediately.
     - Enqueues GENERATE_INSIGHTS background job and produces in-app notification.
  4. In-App Notifications:
     - List notifications for authenticated user with unread_count.
     - GET /api/monitoring/notifications/unread-count.
     - Mark single notification as read.
     - Mark all notifications as read.
     - Delete notification.
     - IDOR Protection: User B cannot read or delete User A's notifications.
  5. Scheduler Execution Loop & Duplicate Prevention:
     - execute_due_schedules_once identifies due schedules and enqueues jobs.
     - Atomic advance of next_run_at prevents duplicate execution on immediate subsequent runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models.background_job import BackgroundJob
from app.models.monitoring_schedule import MonitoringSchedule
from app.models.notification import Notification
from app.models.user import User
from app.schemas.monitoring import MonitoringScheduleCreate, MonitoringScheduleUpdate
from app.services.auth_service import create_session
from app.services.monitoring_service import (
    calculate_next_run_at,
    execute_due_schedules_once,
    monitoring_service,
)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def make_user(db: Session, prefix: str = "p20") -> User:
    u = User(
        email=f"{prefix}_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="hashed_pw_test",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def auth_client(db: Session, user: User) -> AsyncClient:
    raw_token, _ = create_session(db=db, user_id=user.id)
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    c.cookies.set("session_id", raw_token)
    return c


# ---------------------------------------------------------------------------
# 1. Due-Time Calculation Unit Tests
# ---------------------------------------------------------------------------

def test_calculate_next_run_at_daily_same_day():
    """If current UTC hour is earlier than schedule hour, next run is today."""
    base_time = datetime(2026, 10, 15, 6, 30, tzinfo=timezone.utc)
    next_run = calculate_next_run_at(frequency="DAILY", hour_of_day=8, from_time=base_time)
    assert next_run == datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)


def test_calculate_next_run_at_daily_next_day():
    """If current UTC hour is at or past schedule hour, next run is tomorrow."""
    base_time = datetime(2026, 10, 15, 9, 30, tzinfo=timezone.utc)
    next_run = calculate_next_run_at(frequency="DAILY", hour_of_day=8, from_time=base_time)
    assert next_run == datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)


def test_calculate_next_run_at_weekly():
    """Calculates target weekday properly in UTC."""
    # 2026-10-15 is Thursday (ISO weekday 4)
    base_time = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
    # Target Monday (ISO weekday 1)
    next_run = calculate_next_run_at(frequency="WEEKLY", hour_of_day=8, day_of_week=1, from_time=base_time)
    # Next Monday is 2026-10-19
    assert next_run == datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    assert next_run.isoweekday() == 1


# ---------------------------------------------------------------------------
# 2. Schedule CRUD & Authentication / IDOR API Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_schedules_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/monitoring/schedules")
        assert resp.status_code == 401

        resp = await c.post("/api/monitoring/schedules", json={"name": "Test", "frequency": "DAILY", "hour_of_day": 8})
        assert resp.status_code == 401


@pytest.mark.anyio
async def test_create_daily_and_weekly_schedules():
    db = SessionLocal()
    try:
        user = make_user(db, "sched_create")
        async with auth_client(db, user) as c:
            # 1. Create DAILY schedule
            resp_daily = await c.post(
                "/api/monitoring/schedules",
                json={
                    "name": "Daily Morning Audit",
                    "frequency": "DAILY",
                    "hour_of_day": 7,
                    "is_enabled": True,
                },
            )
            assert resp_daily.status_code == 201
            daily_data = resp_daily.json()
            assert daily_data["name"] == "Daily Morning Audit"
            assert daily_data["frequency"] == "DAILY"
            assert daily_data["hour_of_day"] == 7
            assert daily_data["is_enabled"] is True
            assert daily_data["next_run_at"] is not None

            # 2. Create WEEKLY schedule
            resp_weekly = await c.post(
                "/api/monitoring/schedules",
                json={
                    "name": "Weekly Monday Review",
                    "frequency": "WEEKLY",
                    "day_of_week": 1,
                    "hour_of_day": 9,
                    "is_enabled": True,
                },
            )
            assert resp_weekly.status_code == 201
            weekly_data = resp_weekly.json()
            assert weekly_data["name"] == "Weekly Monday Review"
            assert weekly_data["frequency"] == "WEEKLY"
            assert weekly_data["day_of_week"] == 1
            assert weekly_data["next_run_at"] is not None

            # 3. Create WEEKLY without day_of_week should fail validation (422)
            resp_invalid = await c.post(
                "/api/monitoring/schedules",
                json={
                    "name": "Invalid Weekly",
                    "frequency": "WEEKLY",
                    "hour_of_day": 9,
                },
            )
            assert resp_invalid.status_code == 422
    finally:
        db.close()


@pytest.mark.anyio
async def test_schedule_idor_protection():
    """User B cannot view, update, toggle, delete, or trigger User A's schedule."""
    db = SessionLocal()
    try:
        user_a = make_user(db, "user_a")
        user_b = make_user(db, "user_b")

        # Create schedule for User A
        sched_a = monitoring_service.create_schedule(
            db=db,
            user_id=user_a.id,
            payload=MonitoringScheduleCreate(
                name="User A Confidential Schedule",
                frequency="DAILY",
                hour_of_day=8,
            ),
        )

        async with auth_client(db, user_b) as c:
            # 1. User B lists schedules: must NOT see User A's schedule
            resp_list = await c.get("/api/monitoring/schedules")
            assert resp_list.status_code == 200
            schedules = resp_list.json()["schedules"]
            assert all(s["id"] != str(sched_a.id) for s in schedules)

            # 2. User B GET by id -> 404
            resp_get = await c.get(f"/api/monitoring/schedules/{sched_a.id}")
            assert resp_get.status_code == 404

            # 3. User B PUT update -> 404
            resp_put = await c.put(f"/api/monitoring/schedules/{sched_a.id}", json={"name": "Hacked"})
            assert resp_put.status_code == 404

            # 4. User B toggle -> 404
            resp_toggle = await c.post(f"/api/monitoring/schedules/{sched_a.id}/toggle")
            assert resp_toggle.status_code == 404

            # 5. User B delete -> 404
            resp_del = await c.delete(f"/api/monitoring/schedules/{sched_a.id}")
            assert resp_del.status_code == 404

            # 6. User B trigger -> 404
            resp_trig = await c.post(f"/api/monitoring/schedules/{sched_a.id}/trigger")
            assert resp_trig.status_code == 404
    finally:
        db.close()


@pytest.mark.anyio
async def test_schedule_update_toggle_delete():
    db = SessionLocal()
    try:
        user = make_user(db, "sched_ops")
        async with auth_client(db, user) as c:
            # Create schedule
            resp = await c.post(
                "/api/monitoring/schedules",
                json={"name": "Initial Name", "frequency": "DAILY", "hour_of_day": 10},
            )
            assert resp.status_code == 201
            sched_id = resp.json()["id"]

            # Update schedule
            resp_up = await c.put(
                f"/api/monitoring/schedules/{sched_id}",
                json={"name": "Updated Name", "hour_of_day": 14},
            )
            assert resp_up.status_code == 200
            assert resp_up.json()["name"] == "Updated Name"
            assert resp_up.json()["hour_of_day"] == 14

            # Toggle disabled
            resp_toggle1 = await c.post(f"/api/monitoring/schedules/{sched_id}/toggle")
            assert resp_toggle1.status_code == 200
            assert resp_toggle1.json()["is_enabled"] is False
            assert resp_toggle1.json()["next_run_at"] is None

            # Toggle enabled
            resp_toggle2 = await c.post(f"/api/monitoring/schedules/{sched_id}/toggle")
            assert resp_toggle2.status_code == 200
            assert resp_toggle2.json()["is_enabled"] is True
            assert resp_toggle2.json()["next_run_at"] is not None

            # Safe Delete
            resp_del = await c.delete(f"/api/monitoring/schedules/{sched_id}")
            assert resp_del.status_code == 200

            # Verify 404 after deletion
            resp_get = await c.get(f"/api/monitoring/schedules/{sched_id}")
            assert resp_get.status_code == 404
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. Manual Schedule Trigger & Job/Notification Generation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_trigger_schedule_now():
    db = SessionLocal()
    try:
        user = make_user(db, "sched_trig")
        async with auth_client(db, user) as c:
            create_resp = await c.post(
                "/api/monitoring/schedules",
                json={"name": "Manual Run Schedule", "frequency": "DAILY", "hour_of_day": 12},
            )
            sched_id = create_resp.json()["id"]

            # Trigger immediate execution
            trig_resp = await c.post(f"/api/monitoring/schedules/{sched_id}/trigger")
            assert trig_resp.status_code == 200
            trig_data = trig_resp.json()
            assert trig_data["last_run_at"] is not None

            # Check that a BackgroundJob was enqueued
            jobs = (
                db.query(BackgroundJob)
                .filter(BackgroundJob.user_id == user.id, BackgroundJob.job_type == "GENERATE_INSIGHTS")
                .all()
            )
            assert len(jobs) >= 1

            # Check that an in-app Notification was produced
            notifs_resp = await c.get("/api/monitoring/notifications")
            assert notifs_resp.status_code == 200
            notifs = notifs_resp.json()["notifications"]
            assert len(notifs) >= 1
            assert any("Manual Run Schedule" in n["title"] for n in notifs)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. In-App Notifications API & IDOR Protection Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_notifications_crud_and_idor():
    db = SessionLocal()
    try:
        user_a = make_user(db, "notif_a")
        user_b = make_user(db, "notif_b")

        # Create 2 notifications for User A
        n1 = monitoring_service.create_notification(
            db, user_id=user_a.id, schedule_id=None,
            notification_type="INSIGHT_GENERATED", title="Alert 1", body="Body 1"
        )
        n2 = monitoring_service.create_notification(
            db, user_id=user_a.id, schedule_id=None,
            notification_type="INSIGHT_GENERATED", title="Alert 2", body="Body 2"
        )

        async with auth_client(db, user_a) as c_a:
            # 1. Unread count should be 2
            resp_cnt = await c_a.get("/api/monitoring/notifications/unread-count")
            assert resp_cnt.status_code == 200
            assert resp_cnt.json()["unread_count"] == 2

            # 2. Mark n1 as read
            resp_read = await c_a.patch(f"/api/monitoring/notifications/{n1.id}/read")
            assert resp_read.status_code == 200
            assert resp_read.json()["is_read"] is True

            # 3. Unread count now 1
            resp_cnt2 = await c_a.get("/api/monitoring/notifications/unread-count")
            assert resp_cnt2.json()["unread_count"] == 1

            # 4. Mark all read
            resp_all = await c_a.post("/api/monitoring/notifications/mark-all-read")
            assert resp_all.status_code == 200
            assert resp_all.json()["marked_count"] == 1

            resp_cnt3 = await c_a.get("/api/monitoring/notifications/unread-count")
            assert resp_cnt3.json()["unread_count"] == 0

        # User B IDOR protection checks
        async with auth_client(db, user_b) as c_b:
            # User B must see 0 notifications
            resp_b_list = await c_b.get("/api/monitoring/notifications")
            assert resp_b_list.json()["total_count"] == 0

            # User B cannot mark User A's notification as read
            resp_b_mark = await c_b.patch(f"/api/monitoring/notifications/{n1.id}/read")
            assert resp_b_mark.status_code == 404

            # User B cannot delete User A's notification
            resp_b_del = await c_b.delete(f"/api/monitoring/notifications/{n1.id}")
            assert resp_b_del.status_code == 404

        # User A deletes n1
        async with auth_client(db, user_a) as c_a:
            resp_del = await c_a.delete(f"/api/monitoring/notifications/{n1.id}")
            assert resp_del.status_code == 200
            # Verify deletion
            resp_a_list = await c_a.get("/api/monitoring/notifications")
            assert resp_a_list.json()["total_count"] == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. Automated Scheduler Execution & Duplicate Prevention
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_scheduler_execution_and_duplicate_prevention():
    """execute_due_schedules_once processes due schedules and prevents double-firing."""
    db = SessionLocal()
    try:
        user = make_user(db, "sched_loop")
        now = datetime.now(timezone.utc)

        # Create schedule with next_run_at in the PAST (i.e. due)
        due_schedule = MonitoringSchedule(
            user_id=user.id,
            name="Overdue Daily Check",
            frequency="DAILY",
            hour_of_day=8,
            is_enabled=True,
            next_run_at=now - timedelta(minutes=15),  # 15 minutes overdue
        )
        db.add(due_schedule)
        db.commit()
        db.refresh(due_schedule)

        # Run scheduler execution pass
        executed = await execute_due_schedules_once()
        assert executed >= 1

        # Verify schedule was updated with future next_run_at
        db.refresh(due_schedule)
        assert due_schedule.last_run_at is not None
        assert due_schedule.next_run_at > now

        # Run scheduler execution pass IMMEDIATELY again: should process 0 schedules!
        executed_second_pass = await execute_due_schedules_once()
        assert executed_second_pass == 0, "Duplicate execution must be prevented on subsequent passes"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 6. Background Job Completion Notifications & Idempotency Tests
# ---------------------------------------------------------------------------

def test_job_completion_notification_with_insights():
    """Successful financial analysis job generates INSIGHT_SUMMARY with evidence and risk levels."""
    db = SessionLocal()
    try:
        user = make_user(db, "job_succ")
        job = BackgroundJob(
            user_id=user.id,
            job_type="GENERATE_INSIGHTS",
            status="COMPLETED",
            result_payload={
                "schedule_name": "Weekly Audit",
                "insights_generated": 3,
                "data_sufficient": True,
                "insights_summary": [
                    {
                        "id": "ins-1",
                        "title": "Dining Out Spending Increased",
                        "severity": "HIGH",
                        "insight_type": "SPENDING_INCREASE",
                        "description": "Dining spending rose by 32% this month.",
                        "currency": "LKR",
                        "change_amount": 15000.0,
                        "change_percent": 32.5,
                        "confidence": 0.95,
                    },
                    {
                        "id": "ins-2",
                        "title": "Savings Rate Dropped",
                        "severity": "MEDIUM",
                        "insight_type": "SAVINGS_RATE_DROP",
                        "description": "Savings rate fell from 20% to 12%.",
                        "currency": "LKR",
                        "change_amount": -8.0,
                        "change_percent": -40.0,
                        "confidence": 0.88,
                    },
                    {
                        "id": "ins-3",
                        "title": "Cash Flow Deterioration",
                        "severity": "CRITICAL",
                        "insight_type": "CASH_FLOW_DETERIORATION",
                        "description": "Net monthly cash flow became negative.",
                        "currency": "LKR",
                        "change_amount": -25000.0,
                        "change_percent": -150.0,
                        "confidence": 0.92,
                    },
                ],
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        notif = monitoring_service.handle_job_completion(db, job)
        assert notif is not None
        assert notif.user_id == user.id
        assert notif.notification_type == "INSIGHT_SUMMARY"
        assert "Weekly Audit" in notif.title
        assert "3 insights found" in notif.title
        assert "Highest Risk: CRITICAL" in notif.body
        assert "Dining Out Spending Increased" in notif.body
        assert "Savings Rate Dropped" in notif.body
        assert "Cash Flow Deterioration" in notif.body
        assert f"Job #{str(job.id)[:8]}" in notif.body
        assert job.result_payload.get("completion_notification_id") == str(notif.id)
    finally:
        db.close()


def test_job_completion_notification_no_significant_insights():
    """When financial analysis finds 0 insights, generates truthful MONITORING_NO_CHANGE notification."""
    db = SessionLocal()
    try:
        user = make_user(db, "job_nochange")
        job = BackgroundJob(
            user_id=user.id,
            job_type="GENERATE_INSIGHTS",
            status="COMPLETED",
            parameters={"schedule_name": "Weekly Review"},
            result_payload={
                "schedule_name": "Weekly Review",
                "insights_generated": 0,
                "data_sufficient": True,
                "insights_summary": [],
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        notif = monitoring_service.handle_job_completion(db, job)
        assert notif is not None
        assert notif.notification_type == "MONITORING_NO_CHANGE"
        assert "Stable" in notif.title
        assert "Weekly financial review completed for 'Weekly Review'" in notif.body
        assert "No significant changes were detected in the available data." in notif.body
        assert f"Job #{str(job.id)[:8]}" in notif.body
    finally:
        db.close()


def test_job_failure_notification_sanitized():
    """Failed job notification does not expose stack traces, secrets, or internal paths."""
    db = SessionLocal()
    try:
        user = make_user(db, "job_fail")
        sensitive_trace = (
            "Traceback (most recent call last):\n"
            "  File 'c:/secrets/prod_database.py', line 99, in connect\n"
            "    raise ConnectionError('db_password=SuperSecretPassword123 timeout')"
        )
        job = BackgroundJob(
            user_id=user.id,
            job_type="GENERATE_INSIGHTS",
            status="FAILED",
            error_message=sensitive_trace,
            parameters={"schedule_name": "Monthly Check"},
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        notif = monitoring_service.handle_job_failure(db, job)
        assert notif is not None
        assert notif.notification_type == "JOB_FAILED"
        assert "Monitoring Failed: Monthly Check" in notif.title
        # Critical security assertions: stack traces and secrets are NOT exposed
        assert "Traceback" not in notif.body
        assert "SuperSecretPassword123" not in notif.body
        assert "secrets/prod_database.py" not in notif.body
        assert f"Job #{str(job.id)[:8]}" in notif.body
        assert "encountered an error and could not complete" in notif.body
        assert "account connections remain secure" in notif.body
    finally:
        db.close()


def test_job_completion_notification_idempotency_prevents_duplicates():
    """Duplicate processing or retries of the same job never create duplicate notifications."""
    db = SessionLocal()
    try:
        user = make_user(db, "job_idem")
        job = BackgroundJob(
            user_id=user.id,
            job_type="GENERATE_INSIGHTS",
            status="COMPLETED",
            parameters={"schedule_name": "Biweekly Audit"},
            result_payload={
                "schedule_name": "Biweekly Audit",
                "insights_generated": 1,
                "data_sufficient": True,
                "insights_summary": [
                    {
                        "id": "ins-9",
                        "title": "Subscription Increase",
                        "severity": "LOW",
                        "insight_type": "RECURRING_EXPENSE_INCREASE",
                        "description": "Streaming bill increased by $2.",
                        "currency": "USD",
                    }
                ],
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        first_notif = monitoring_service.handle_job_completion(db, job)
        assert first_notif is not None

        # Call again as if the worker retried or re-processed the event
        second_notif = monitoring_service.handle_job_completion(db, job)
        # Should return existing notification and not create a duplicate in DB
        assert second_notif is not None
        assert second_notif.id == first_notif.id

        total_notifs = db.query(Notification).filter(Notification.user_id == user.id).count()
        assert total_notifs == 1, "Duplicate notifications must be prevented"
    finally:
        db.close()


@pytest.mark.anyio
async def test_job_completion_notification_user_isolation():
    """User B cannot view or access User A's job completion notifications."""
    db = SessionLocal()
    try:
        user_a = make_user(db, "job_iso_a")
        user_b = make_user(db, "job_iso_b")

        job_a = BackgroundJob(
            user_id=user_a.id,
            job_type="GENERATE_INSIGHTS",
            status="COMPLETED",
            parameters={"schedule_name": "User A Private Schedule"},
            result_payload={
                "schedule_name": "User A Private Schedule",
                "insights_generated": 1,
                "data_sufficient": True,
                "insights_summary": [
                    {
                        "id": "ins-a",
                        "title": "Private Salary Review",
                        "severity": "HIGH",
                        "insight_type": "SPENDING_INCREASE",
                        "description": "User A private financial data",
                        "currency": "EUR",
                    }
                ],
            },
        )
        db.add(job_a)
        db.commit()
        db.refresh(job_a)

        notif_a = monitoring_service.handle_job_completion(db, job_a)
        assert notif_a is not None

        # User B queries their notifications
        async with auth_client(db, user_b) as c_b:
            resp_b = await c_b.get("/api/monitoring/notifications")
            assert resp_b.status_code == 200
            data_b = resp_b.json()
            assert data_b["total_count"] == 0
            assert len(data_b["notifications"]) == 0

            # User B attempts to mark User A's notification as read
            resp_mark = await c_b.patch(f"/api/monitoring/notifications/{notif_a.id}/read")
            assert resp_mark.status_code == 404

        # User A can see their notification
        async with auth_client(db, user_a) as c_a:
            resp_a = await c_a.get("/api/monitoring/notifications")
            assert resp_a.status_code == 200
            data_a = resp_a.json()
            assert data_a["total_count"] == 1
            assert data_a["notifications"][0]["id"] == str(notif_a.id)
            assert "User A Private Schedule" in data_a["notifications"][0]["title"]
    finally:
        db.close()
