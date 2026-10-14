"""Phase 19 — Background Processing System API routes.

Endpoints:
  POST   /api/jobs                    — Submit a new background job
  GET    /api/jobs                    — List authenticated user's jobs
  GET    /api/jobs/{job_id}           — Get status of a specific job
  POST   /api/jobs/{job_id}/cancel    — Cancel a queued or running job
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.background_jobs import (
    BackgroundJobResponse,
    JobCancelRequest,
    JobCancelResponse,
    JobListResponse,
    JobSubmitRequest,
    JobSubmitResponse,
)
from app.services.background_jobs import background_job_service

router = APIRouter(prefix="/api/jobs", tags=["background-jobs"])

_VALID_JOB_TYPES = {
    "ANALYZE_TRANSACTIONS",
    "GENERATE_INSIGHTS",
    "DOCUMENT_REPROCESS",
    "PORTFOLIO_RECALCULATION",
}


@router.post(
    "",
    response_model=JobSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="[Phase 19] Submit a background processing job",
)
def submit_job(
    request_data: JobSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobSubmitResponse:
    """Submit a long-running financial processing task for background execution.

    Security Invariants:
    - Session authentication required.
    - job_type validated against the allowlist — unknown types are rejected.
    - parameters are stored verbatim; callers should not embed credentials.
    - The returned job_id is scoped to the authenticated user and cannot be
      used to access another user's job data.
    """
    if request_data.job_type not in _VALID_JOB_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown job_type={request_data.job_type!r}. "
            f"Valid types: {sorted(_VALID_JOB_TYPES)}",
        )

    job = background_job_service.submit_job(
        db=db,
        user_id=current_user.id,
        job_type=request_data.job_type,
        parameters=request_data.parameters,
    )

    return JobSubmitResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        message=f"Job {job.id} accepted and queued for processing.",
    )


@router.get(
    "",
    response_model=JobListResponse,
    summary="[Phase 19] List background jobs for the authenticated user",
)
def list_jobs(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by job status (QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED).",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobListResponse:
    """Retrieve all background jobs for the authenticated user.

    Security Invariants:
    - Results are hard-filtered to current_user.id; no cross-user data leaks.
    - status_filter is validated against the enum before being used in a query.
    """
    _VALID_STATUSES = {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}
    if status_filter and status_filter not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status={status_filter!r}. Valid: {sorted(_VALID_STATUSES)}",
        )

    jobs, total, counts = background_job_service.list_jobs(
        db=db,
        user_id=current_user.id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )

    return JobListResponse(
        jobs=[BackgroundJobResponse.model_validate(j) for j in jobs],
        total_count=total,
        queued_count=counts.get("QUEUED", 0),
        running_count=counts.get("RUNNING", 0),
        completed_count=counts.get("COMPLETED", 0),
        failed_count=counts.get("FAILED", 0),
    )


@router.get(
    "/{job_id}",
    response_model=BackgroundJobResponse,
    summary="[Phase 19] Get status of a specific background job",
)
def get_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BackgroundJobResponse:
    """Fetch status and result of a single background job.

    Security Invariants:
    - get_job() enforces user_id == current_user.id — IDOR protection.
    - Returns 404 for non-existent or foreign jobs (no information leakage).
    """
    job = background_job_service.get_job(db=db, job_id=job_id, user_id=current_user.id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )
    return BackgroundJobResponse.model_validate(job)


@router.post(
    "/{job_id}/cancel",
    response_model=JobCancelResponse,
    summary="[Phase 19] Cancel a queued or running background job",
)
def cancel_job(
    job_id: uuid.UUID,
    request_data: JobCancelRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobCancelResponse:
    """Request cancellation of a background job.

    Security Invariants:
    - Ownership verified via get_job(user_id=current_user.id).
    - COMPLETED/FAILED jobs cannot be cancelled (409 Conflict).
    - Only the owning user can cancel their own jobs.
    """
    job = background_job_service.get_job(db=db, job_id=job_id, user_id=current_user.id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )

    if job.status not in ("QUEUED", "RUNNING"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel job in status={job.status!r}. Only QUEUED or RUNNING jobs can be cancelled.",
        )

    cancelled = background_job_service.cancel_job(
        db=db, job_id=job_id, user_id=current_user.id
    )
    if cancelled is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job could not be cancelled.",
        )

    return JobCancelResponse(
        job_id=cancelled.id,
        status=cancelled.status,
        message="Job cancellation requested.",
    )
