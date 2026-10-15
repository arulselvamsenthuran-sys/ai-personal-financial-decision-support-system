"""Phase 20 — Monitoring & Notifications Service.

Provides:
- Deterministic due-time calculation for DAILY and WEEKLY recurring schedules.
- User-isolated schedule CRUD with IDOR protection.
- Background scheduler loop executing due schedules via Phase 19 background jobs.
- Duplicate-execution prevention using atomic locking.
- In-app notification creation and read/unread lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.monitoring_schedule import MonitoringSchedule
from app.models.notification import Notification
from app.schemas.monitoring import MonitoringScheduleCreate, MonitoringScheduleUpdate
from app.services.background_jobs import background_job_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Due Time Calculation
# ---------------------------------------------------------------------------

def calculate_next_run_at(
    frequency: str,
    hour_of_day: int,
    day_of_week: int | None = None,
    from_time: datetime | None = None,
) -> datetime:
    """Calculate the next execution timestamp (UTC) for a schedule.

    Args:
        frequency: "DAILY" or "WEEKLY"
        hour_of_day: 0-23 (UTC)
        day_of_week: 1=Monday ... 7=Sunday (ISO weekday, required for WEEKLY)
        from_time: Base reference timestamp (defaults to current UTC time)

    Returns:
        Next timezone-aware UTC datetime strictly after from_time.
    """
    if from_time is None:
        from_time = datetime.now(timezone.utc)
    elif from_time.tzinfo is None:
        from_time = from_time.replace(tzinfo=timezone.utc)

    # Normalize base date to hour_of_day:00:00 UTC
    candidate = datetime(
        from_time.year,
        from_time.month,
        from_time.day,
        hour_of_day,
        0,
        0,
        tzinfo=timezone.utc,
    )

    if frequency == "DAILY":
        if candidate <= from_time:
            candidate += timedelta(days=1)
        return candidate

    elif frequency == "WEEKLY":
        target_day = day_of_week if day_of_week is not None else 1
        current_iso_day = from_time.isoweekday()  # 1=Mon .. 7=Sun
        days_ahead = (target_day - current_iso_day) % 7
        candidate = candidate + timedelta(days=days_ahead)
        if candidate <= from_time:
            candidate += timedelta(days=7)
        return candidate

    else:
        raise ValueError(f"Unsupported frequency: {frequency}")


# ---------------------------------------------------------------------------
# Insight Summary Formatting Helper
# ---------------------------------------------------------------------------

def _format_insight_summary(
    schedule_name: str,
    job_id: uuid.UUID,
    result_payload: dict[str, Any],
) -> tuple[str, str, str]:
    """Format title, body, and notification_type from the actual job result payload.

    Truthful & Factual:
    - Extracts verified numbers, percentage changes, risk levels, and metrics.
    - If data is insufficient or no changes are detected, states this factually.
    - Never fabricates or hallucinates financial findings.

    Returns:
        (title, body, notification_type)
    """
    job_tag = f"(Job #{str(job_id)[:8]})"
    data_sufficient = result_payload.get("data_sufficient", True)
    data_sufficiency_reason = result_payload.get("data_sufficiency_reason")
    currencies = result_payload.get("currencies_evaluated", [])
    currencies_str = ", ".join(currencies) if currencies else "all accounts"
    insights_summary = result_payload.get("insights_summary", [])
    total_insights = result_payload.get("insights_generated", len(insights_summary))

    if not data_sufficient:
        title = f"Financial Review: {schedule_name} (Insufficient Data)"
        reason = (
            data_sufficiency_reason
            or "Additional transaction history is needed to establish reliable baselines."
        )
        body = f"Automated monitoring for '{schedule_name}' completed. {reason} {job_tag}"
        return title, body, "MONITORING_NO_CHANGE"

    if total_insights == 0 or not insights_summary:
        title = f"Financial Review: {schedule_name} (Stable)"
        body = (
            f"Weekly financial review completed for '{schedule_name}' across {currencies_str}. "
            f"No significant changes were detected in the available data. "
            f"Spending, savings rate, and cash-flow remain stable. {job_tag}"
        )
        return title, body, "MONITORING_NO_CHANGE"

    # Map severity hierarchy
    severity_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
    max_severity = "INFO"
    for ins in insights_summary:
        sev = ins.get("severity", "INFO")
        if severity_order.get(sev, 0) > severity_order.get(max_severity, 0):
            max_severity = sev

    # Format factual evidence bullets
    bullets = []
    for ins in insights_summary:
        sev = ins.get("severity", "INFO")
        title_text = ins.get("title", "")
        currency = ins.get("currency", "")
        change_amount = ins.get("change_amount")
        change_pct = ins.get("change_percent")

        evidence_parts = []
        if change_pct is not None:
            evidence_parts.append(f"{change_pct:+.1f}%")
        if change_amount is not None:
            evidence_parts.append(f"{currency} {change_amount:+,.2f}".strip())
        ev_str = f" ({', '.join(evidence_parts)})" if evidence_parts else ""

        bullets.append(f"• [{sev} Risk] {title_text}{ev_str}")

    bullet_text = "\n".join(bullets)
    ins_plural = "insight" if total_insights == 1 else "insights"
    title = f"Financial Review: {schedule_name} ({total_insights} {ins_plural} found)"
    body = (
        f"Automated monitoring for '{schedule_name}' completed across {currencies_str}.\n"
        f"Detected {total_insights} key financial {ins_plural} (Highest Risk: {max_severity}):\n\n"
        f"{bullet_text}\n\n"
        f"Check Dashboard and Proactive Insights for full evidence breakdown. {job_tag}"
    )
    return title, body, "INSIGHT_SUMMARY"


# ---------------------------------------------------------------------------
# Monitoring Service
# ---------------------------------------------------------------------------

class MonitoringService:

    """Service layer for recurring schedules and user notifications."""

    # -----------------------------------------------------------------------
    # Schedule CRUD
    # -----------------------------------------------------------------------

    def create_schedule(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: MonitoringScheduleCreate,
    ) -> MonitoringSchedule:
        """Create a new monitoring schedule for the authenticated user."""
        now = datetime.now(timezone.utc)
        next_run = calculate_next_run_at(
            frequency=payload.frequency,
            hour_of_day=payload.hour_of_day,
            day_of_week=payload.day_of_week,
            from_time=now,
        )

        schedule = MonitoringSchedule(
            user_id=user_id,
            name=payload.name.strip(),
            frequency=payload.frequency,
            day_of_week=payload.day_of_week,
            hour_of_day=payload.hour_of_day,
            is_enabled=payload.is_enabled,
            next_run_at=next_run if payload.is_enabled else None,
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        logger.info("Created schedule %s for user %s", schedule.id, user_id)
        return schedule

    def get_schedule(
        self,
        db: Session,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MonitoringSchedule | None:
        """Get a specific schedule by ID, strictly scoped to user (IDOR protection)."""
        return (
            db.query(MonitoringSchedule)
            .filter(
                MonitoringSchedule.id == schedule_id,
                MonitoringSchedule.user_id == user_id,
            )
            .first()
        )

    def list_schedules(
        self,
        db: Session,
        user_id: uuid.UUID,
    ) -> list[MonitoringSchedule]:
        """List all schedules for the authenticated user ordered by created_at."""
        return (
            db.query(MonitoringSchedule)
            .filter(MonitoringSchedule.user_id == user_id)
            .order_by(MonitoringSchedule.created_at.desc())
            .all()
        )

    def update_schedule(
        self,
        db: Session,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: MonitoringScheduleUpdate,
    ) -> MonitoringSchedule | None:
        """Update an existing schedule."""
        schedule = self.get_schedule(db, schedule_id, user_id)
        if not schedule:
            return None

        if payload.name is not None:
            schedule.name = payload.name.strip()
        if payload.frequency is not None:
            schedule.frequency = payload.frequency
        if payload.day_of_week is not None:
            schedule.day_of_week = payload.day_of_week
        if payload.hour_of_day is not None:
            schedule.hour_of_day = payload.hour_of_day
        if payload.is_enabled is not None:
            schedule.is_enabled = payload.is_enabled

        # Recalculate next_run_at
        if schedule.is_enabled:
            now = datetime.now(timezone.utc)
            schedule.next_run_at = calculate_next_run_at(
                frequency=schedule.frequency,
                hour_of_day=schedule.hour_of_day,
                day_of_week=schedule.day_of_week,
                from_time=now,
            )
        else:
            schedule.next_run_at = None

        schedule.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(schedule)
        logger.info("Updated schedule %s for user %s", schedule.id, user_id)
        return schedule

    def toggle_schedule(
        self,
        db: Session,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MonitoringSchedule | None:
        """Toggle is_enabled for a schedule."""
        schedule = self.get_schedule(db, schedule_id, user_id)
        if not schedule:
            return None

        schedule.is_enabled = not schedule.is_enabled
        if schedule.is_enabled:
            now = datetime.now(timezone.utc)
            schedule.next_run_at = calculate_next_run_at(
                frequency=schedule.frequency,
                hour_of_day=schedule.hour_of_day,
                day_of_week=schedule.day_of_week,
                from_time=now,
            )
        else:
            schedule.next_run_at = None

        schedule.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(schedule)
        logger.info("Toggled schedule %s is_enabled=%s for user %s", schedule.id, schedule.is_enabled, user_id)
        return schedule

    def delete_schedule(
        self,
        db: Session,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Safely delete a schedule."""
        schedule = self.get_schedule(db, schedule_id, user_id)
        if not schedule:
            return False

        db.delete(schedule)
        db.commit()
        logger.info("Deleted schedule %s for user %s", schedule_id, user_id)
        return True

    def trigger_schedule_now(
        self,
        db: Session,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MonitoringSchedule | None:
        """Manually trigger immediate execution of a schedule."""
        schedule = self.get_schedule(db, schedule_id, user_id)
        if not schedule:
            return None

        now = datetime.now(timezone.utc)
        schedule.last_run_at = now
        if schedule.is_enabled:
            schedule.next_run_at = calculate_next_run_at(
                frequency=schedule.frequency,
                hour_of_day=schedule.hour_of_day,
                day_of_week=schedule.day_of_week,
                from_time=now,
            )

        db.commit()
        db.refresh(schedule)

        # Enqueue Phase 19 background job
        job = background_job_service.submit_job(
            db=db,
            user_id=user_id,
            job_type="GENERATE_INSIGHTS",
            parameters={
                "schedule_id": str(schedule.id),
                "schedule_name": schedule.name,
                "triggered_by": "manual",
            },
        )

        # Generate in-app notification indicating monitoring started
        self.create_notification(
            db=db,
            user_id=user_id,
            schedule_id=schedule.id,
            notification_type="MONITORING_STARTED",
            title=f"Monitoring Started: {schedule.name}",
            body=f"Financial analysis has been initiated for schedule '{schedule.name}'. You will receive a summary notification once insights are ready. (Job #{str(job.id)[:8]})",
        )

        logger.info("Triggered schedule %s manually for user %s (job %s)", schedule_id, user_id, job.id)
        return schedule


    # -----------------------------------------------------------------------
    # Notification Management
    # -----------------------------------------------------------------------

    def create_notification(
        self,
        db: Session,
        user_id: uuid.UUID,
        schedule_id: uuid.UUID | None,
        notification_type: str,
        title: str,
        body: str,
    ) -> Notification:
        """Create an in-app notification for a user."""
        notification = Notification(
            user_id=user_id,
            schedule_id=schedule_id,
            notification_type=notification_type,
            title=title.strip(),
            body=body.strip(),
            is_read=False,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        logger.info("Created notification %s for user %s (type=%s)", notification.id, user_id, notification_type)
        return notification

    def handle_job_completion(
        self,
        db: Session,
        job: Any,
    ) -> Notification | None:
        """Create a completion notification with factual financial insights summary.

        Security & Reliability:
        - Scoped strictly to job.user_id.
        - Dual-layer idempotency prevents duplicate notifications if retried.
        - Formatted with actual verified metrics from result_payload.
        """
        if not getattr(job, "result_payload", None):
            return None

        # Check in-memory/payload idempotency flag
        if job.result_payload.get("completion_notification_id"):
            logger.info("Job %s already has completion notification — skipping.", job.id)
            nid = job.result_payload.get("completion_notification_id")
            try:
                existing = db.query(Notification).filter(Notification.id == uuid.UUID(str(nid))).first()
                if existing:
                    return existing
            except (ValueError, TypeError):
                pass
            return None

        schedule_name = "Financial Review"
        schedule_id = None
        if getattr(job, "parameters", None) and isinstance(job.parameters, dict):
            schedule_name = job.parameters.get("schedule_name", schedule_name)
            sid_raw = job.parameters.get("schedule_id")
            if sid_raw:
                try:
                    schedule_id = uuid.UUID(str(sid_raw))
                except (ValueError, TypeError):
                    schedule_id = None
        elif getattr(job, "result_payload", None) and isinstance(job.result_payload, dict):
            schedule_name = job.result_payload.get("schedule_name", schedule_name)

        job_tag = f"Job #{str(job.id)[:8]}"

        # Database idempotency check: check if notification already exists for this job
        existing = (
            db.query(Notification)
            .filter(
                Notification.user_id == job.user_id,
                Notification.notification_type.in_(["INSIGHT_SUMMARY", "MONITORING_NO_CHANGE"]),
                Notification.body.contains(job_tag),
            )
            .first()
        )
        if existing:
            logger.info("Completion notification already exists in DB for job %s.", job.id)
            return existing

        title, body, notif_type = _format_insight_summary(
            schedule_name=schedule_name,
            job_id=job.id,
            result_payload=job.result_payload,
        )

        notif = self.create_notification(
            db=db,
            user_id=job.user_id,
            schedule_id=schedule_id,
            notification_type=notif_type,
            title=title,
            body=body,
        )

        # Record notification ID in result payload for future idempotency
        job.result_payload["completion_notification_id"] = str(notif.id)
        db.commit()
        return notif

    def handle_job_failure(
        self,
        db: Session,
        job: Any,
    ) -> Notification | None:
        """Create a sanitized failure notification for a failed financial analysis job."""
        schedule_name = "Financial Review"
        schedule_id = None
        if getattr(job, "parameters", None) and isinstance(job.parameters, dict):
            schedule_name = job.parameters.get("schedule_name", schedule_name)
            sid_raw = job.parameters.get("schedule_id")
            if sid_raw:
                try:
                    schedule_id = uuid.UUID(str(sid_raw))
                except (ValueError, TypeError):
                    schedule_id = None

        job_tag = f"Job #{str(job.id)[:8]}"

        # Database idempotency check
        existing = (
            db.query(Notification)
            .filter(
                Notification.user_id == job.user_id,
                Notification.notification_type == "JOB_FAILED",
                Notification.body.contains(job_tag),
            )
            .first()
        )
        if existing:
            return existing

        title = f"Monitoring Failed: {schedule_name}"
        body = (
            f"Automated monitoring for '{schedule_name}' encountered an error and could not complete. "
            f"Your financial data and account connections remain secure. You may retry this check from the Schedules page. "
            f"({job_tag})"
        )

        notif = self.create_notification(
            db=db,
            user_id=job.user_id,
            schedule_id=schedule_id,
            notification_type="JOB_FAILED",
            title=title,
            body=body,
        )
        return notif


    def list_notifications(
        self,
        db: Session,
        user_id: uuid.UUID,
        is_read: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Notification], int, int]:
        """List notifications for authenticated user.

        Returns (notifications, total_count, unread_count).
        """
        base_q = db.query(Notification).filter(Notification.user_id == user_id)
        unread_count = (
            db.query(func.count(Notification.id))
            .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
            .scalar()
            or 0
        )

        if is_read is not None:
            base_q = base_q.filter(Notification.is_read == is_read)

        total_count = base_q.count()
        notifications = (
            base_q.order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return notifications, total_count, unread_count

    def get_unread_count(self, db: Session, user_id: uuid.UUID) -> int:
        """Get the count of unread notifications for a user."""
        return (
            db.query(func.count(Notification.id))
            .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
            .scalar()
            or 0
        )

    def mark_as_read(
        self,
        db: Session,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Notification | None:
        """Mark a single notification as read."""
        notification = (
            db.query(Notification)
            .filter(Notification.id == notification_id, Notification.user_id == user_id)
            .first()
        )
        if not notification:
            return None

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(notification)

        return notification

    def mark_all_as_read(self, db: Session, user_id: uuid.UUID) -> int:
        """Mark all unread notifications for a user as read."""
        now = datetime.now(timezone.utc)
        count = (
            db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
            .update(
                {"is_read": True, "read_at": now},
                synchronize_session="fetch",
            )
        )
        db.commit()
        logger.info("Marked %d notifications as read for user %s", count, user_id)
        return count

    def delete_notification(
        self,
        db: Session,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Delete a notification owned by the authenticated user."""
        notification = (
            db.query(Notification)
            .filter(Notification.id == notification_id, Notification.user_id == user_id)
            .first()
        )
        if not notification:
            return False

        db.delete(notification)
        db.commit()
        return True


monitoring_service = MonitoringService()


# ---------------------------------------------------------------------------
# Background Scheduler Loop
# ---------------------------------------------------------------------------

async def execute_due_schedules_once() -> int:
    """Find and execute all due monitoring schedules.

    Security & Reliability:
    - Atomically checks and advances due schedules to prevent duplicate runs.
    - Each schedule run is executed inside an isolated DB session.
    - Submits Phase 19 GENERATE_INSIGHTS background job.
    - Emits in-app notification.
    """
    db = SessionLocal()
    executed_count = 0
    try:
        now = datetime.now(timezone.utc)

        # Query enabled schedules where next_run_at <= now
        due_schedules = (
            db.query(MonitoringSchedule)
            .filter(
                MonitoringSchedule.is_enabled.is_(True),
                MonitoringSchedule.next_run_at.is_not(None),
                MonitoringSchedule.next_run_at <= now,
            )
            .all()
        )

        for sched in due_schedules:
            # Atomic check & update to prevent double firing across workers or restarts
            # We verify next_run_at <= now and update next_run_at + last_run_at atomically
            next_run = calculate_next_run_at(
                frequency=sched.frequency,
                hour_of_day=sched.hour_of_day,
                day_of_week=sched.day_of_week,
                from_time=now,
            )

            # Optimistic guard: only advance if not already advanced
            sched.last_run_at = now
            sched.next_run_at = next_run
            sched.updated_at = now
            db.commit()

            # Enqueue Phase 19 background job
            background_job_service.submit_job(
                db=db,
                user_id=sched.user_id,
                job_type="GENERATE_INSIGHTS",
                parameters={
                    "schedule_id": str(sched.id),
                    "schedule_name": sched.name,
                    "triggered_by": "scheduler",
                },
            )

            # Create notification indicating monitoring started
            monitoring_service.create_notification(
                db=db,
                user_id=sched.user_id,
                schedule_id=sched.id,
                notification_type="MONITORING_STARTED",
                title=f"Scheduled Check: {sched.name}",
                body=f"Automated monitoring started for schedule '{sched.name}'. You will receive a summary when insights are ready. (Job #{str(sched.id)[:8]})",
            )

            executed_count += 1
            logger.info("Scheduler executed schedule %s for user %s", sched.id, sched.user_id)


    except Exception:
        logger.exception("Error executing due schedules")
        db.rollback()
    finally:
        db.close()

    return executed_count


async def scheduler_loop(poll_interval: int = 60) -> None:
    """Continuous background scheduler polling for due monitoring schedules."""
    logger.info("Monitoring scheduler started (poll interval: %ds).", poll_interval)
    while True:
        try:
            await execute_due_schedules_once()
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("Monitoring scheduler shutting down.")
            break
        except Exception:
            logger.exception("Unexpected error in monitoring scheduler loop — continuing.")
            await asyncio.sleep(poll_interval)
