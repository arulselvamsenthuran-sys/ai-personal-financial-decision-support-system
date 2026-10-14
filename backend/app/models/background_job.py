"""Phase 19 — Background Job Model.

Tracks the lifecycle of long-running financial processing tasks.
Each job is strictly scoped to an authenticated user (user_id FK).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BackgroundJob(Base):
    """Persistent record of a background processing job.

    Security Invariants:
    - user_id is a non-nullable FK to users.id — every job is owned.
    - Queries MUST always filter by user_id alongside job_id (IDOR protection).
    - result_payload and error_message are stored as opaque blobs; no sensitive
      credentials or session tokens must ever be written into these fields.
    """

    __tablename__ = "background_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Job classification
    job_type: Mapped[str] = mapped_column(
        Enum(
            "ANALYZE_TRANSACTIONS",
            "GENERATE_INSIGHTS",
            "DOCUMENT_REPROCESS",
            "PORTFOLIO_RECALCULATION",
            name="background_job_type_enum",
        ),
        nullable=False,
    )

    # Lifecycle state
    status: Mapped[str] = mapped_column(
        Enum(
            "QUEUED",
            "RUNNING",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
            name="background_job_status_enum",
        ),
        nullable=False,
        default="QUEUED",
        index=True,
    )

    # Progress tracking (0–100)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Input parameters (caller-supplied, e.g. {"account_id": "..."})
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Outputs
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="background_jobs")  # type: ignore[name-defined]

    __table_args__ = (
        Index("ix_background_jobs_user_status", "user_id", "status"),
        Index("ix_background_jobs_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<BackgroundJob id={self.id} type={self.job_type} status={self.status}>"
        )
