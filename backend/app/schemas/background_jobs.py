"""Phase 19 — Background Processing System Pydantic schemas.

Request / Response models for the background-jobs API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Job type and status enumerations (mirrored from the ORM enums)
# ---------------------------------------------------------------------------

JobType = Literal[
    "ANALYZE_TRANSACTIONS",
    "GENERATE_INSIGHTS",
    "DOCUMENT_REPROCESS",
    "PORTFOLIO_RECALCULATION",
]

JobStatus = Literal[
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class JobSubmitRequest(BaseModel):
    """Submit a new background processing job."""

    job_type: JobType = Field(
        ...,
        description="Type of background processing to perform.",
    )
    parameters: dict[str, Any] | None = Field(
        default=None,
        description="Optional job-type-specific input parameters.",
    )


class JobCancelRequest(BaseModel):
    """Request to cancel a queued or running job."""

    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Optional human-readable cancellation reason.",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class BackgroundJobResponse(BaseModel):
    """Representation of a single background job."""

    id: uuid.UUID
    job_type: str
    status: str
    progress_pct: int
    progress_message: str | None
    parameters: dict[str, Any] | None
    result_payload: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class JobSubmitResponse(BaseModel):
    """Confirmation that a job was accepted."""

    job_id: uuid.UUID
    job_type: str
    status: str
    message: str


class JobListResponse(BaseModel):
    """Paginated list of background jobs for the authenticated user."""

    jobs: list[BackgroundJobResponse]
    total_count: int
    queued_count: int
    running_count: int
    completed_count: int
    failed_count: int


class JobCancelResponse(BaseModel):
    """Confirmation that a job was cancelled."""

    job_id: uuid.UUID
    status: str
    message: str
