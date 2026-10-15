"""Phase 20 — Monitoring Schedule ORM Model.

Represents a user-configured recurring schedule that enqueues background jobs
(Phase 19) to run proactive financial analysis automatically.

Security Invariants:
- user_id is a non-nullable FK to users.id — every schedule is owned.
- Queries MUST always filter by user_id alongside schedule_id (IDOR protection).
- Scheduler only enqueues jobs for enabled schedules owned by the correct user.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class MonitoringSchedule(Base):
    """A recurring schedule for automated financial monitoring.

    Supported frequencies: DAILY, WEEKLY.
    When enabled and due, the scheduler enqueues a GENERATE_INSIGHTS background
    job (Phase 19). The is_enabled flag lets users pause without deleting.
    """

    __tablename__ = "monitoring_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Human-readable label (e.g. "Daily Portfolio Check")
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Frequency: DAILY or WEEKLY
    frequency: Mapped[str] = mapped_column(
        Enum("DAILY", "WEEKLY", name="monitoring_frequency_enum"),
        nullable=False,
    )

    # For WEEKLY schedules: ISO weekday (1=Monday … 7=Sunday)
    day_of_week: Mapped[int | None] = mapped_column(nullable=True)

    # Hour of day for execution (0–23, UTC)
    hour_of_day: Mapped[int] = mapped_column(nullable=False, default=8)

    # Whether this schedule is active
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Lifecycle timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Last time a job was enqueued for this schedule (used for duplicate prevention)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Next scheduled execution time (UTC, computed on creation/update/run)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="monitoring_schedules")

    __table_args__ = (
        Index("ix_monitoring_schedules_user_id", "user_id"),
        Index("ix_monitoring_schedules_next_run", "next_run_at"),
        Index("ix_monitoring_schedules_user_enabled", "user_id", "is_enabled"),
    )

    def __repr__(self) -> str:
        return (
            f"<MonitoringSchedule id={self.id} freq={self.frequency} "
            f"enabled={self.is_enabled} next={self.next_run_at}>"
        )
