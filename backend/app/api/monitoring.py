"""Phase 20 — Scheduled Financial Monitoring and Notifications API routes.

Endpoints:
  Schedules:
    POST   /api/monitoring/schedules                  — Create monitoring schedule
    GET    /api/monitoring/schedules                  — List user schedules
    GET    /api/monitoring/schedules/{schedule_id}    — Get specific schedule
    PUT    /api/monitoring/schedules/{schedule_id}    — Update schedule
    POST   /api/monitoring/schedules/{schedule_id}/toggle — Toggle active state
    DELETE /api/monitoring/schedules/{schedule_id}    — Safely delete schedule
    POST   /api/monitoring/schedules/{schedule_id}/trigger — Run schedule immediately

  Notifications:
    GET    /api/monitoring/notifications              — List in-app notifications
    GET    /api/monitoring/notifications/unread-count — Count unread notifications
    PATCH  /api/monitoring/notifications/{notification_id}/read — Mark single as read
    POST   /api/monitoring/notifications/mark-all-read — Mark all as read
    DELETE /api/monitoring/notifications/{notification_id} — Delete notification
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.monitoring import (
    MarkReadResponse,
    MonitoringScheduleCreate,
    MonitoringScheduleListResponse,
    MonitoringScheduleResponse,
    MonitoringScheduleUpdate,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from app.services.monitoring_service import monitoring_service

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


# ---------------------------------------------------------------------------
# Schedule Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/schedules",
    response_model=MonitoringScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Phase 20] Create a recurring monitoring schedule",
)
def create_schedule(
    payload: MonitoringScheduleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonitoringScheduleResponse:
    """Create a new daily or weekly financial monitoring schedule."""
    schedule = monitoring_service.create_schedule(
        db=db,
        user_id=current_user.id,
        payload=payload,
    )
    return MonitoringScheduleResponse.model_validate(schedule)


@router.get(
    "/schedules",
    response_model=MonitoringScheduleListResponse,
    summary="[Phase 20] List user monitoring schedules",
)
def list_schedules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonitoringScheduleListResponse:
    """List all recurring monitoring schedules owned by the authenticated user."""
    schedules = monitoring_service.list_schedules(db=db, user_id=current_user.id)
    return MonitoringScheduleListResponse(
        schedules=[MonitoringScheduleResponse.model_validate(s) for s in schedules],
        total_count=len(schedules),
    )


@router.get(
    "/schedules/{schedule_id}",
    response_model=MonitoringScheduleResponse,
    summary="[Phase 20] Get details of a monitoring schedule",
)
def get_schedule(
    schedule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonitoringScheduleResponse:
    """Get a specific schedule by ID, strictly enforcing user ownership."""
    schedule = monitoring_service.get_schedule(
        db=db,
        schedule_id=schedule_id,
        user_id=current_user.id,
    )
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitoring schedule not found.",
        )
    return MonitoringScheduleResponse.model_validate(schedule)


@router.put(
    "/schedules/{schedule_id}",
    response_model=MonitoringScheduleResponse,
    summary="[Phase 20] Update a monitoring schedule",
)
def update_schedule(
    schedule_id: uuid.UUID,
    payload: MonitoringScheduleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonitoringScheduleResponse:
    """Update a monitoring schedule."""
    schedule = monitoring_service.update_schedule(
        db=db,
        schedule_id=schedule_id,
        user_id=current_user.id,
        payload=payload,
    )
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitoring schedule not found.",
        )
    return MonitoringScheduleResponse.model_validate(schedule)


@router.post(
    "/schedules/{schedule_id}/toggle",
    response_model=MonitoringScheduleResponse,
    summary="[Phase 20] Enable or disable a monitoring schedule",
)
def toggle_schedule(
    schedule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonitoringScheduleResponse:
    """Toggle the enabled status of a schedule."""
    schedule = monitoring_service.toggle_schedule(
        db=db,
        schedule_id=schedule_id,
        user_id=current_user.id,
    )
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitoring schedule not found.",
        )
    return MonitoringScheduleResponse.model_validate(schedule)


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_200_OK,
    summary="[Phase 20] Safely delete a monitoring schedule",
)
def delete_schedule(
    schedule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Safely delete a monitoring schedule."""
    deleted = monitoring_service.delete_schedule(
        db=db,
        schedule_id=schedule_id,
        user_id=current_user.id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitoring schedule not found.",
        )
    return {"message": "Schedule deleted successfully."}


@router.post(
    "/schedules/{schedule_id}/trigger",
    response_model=MonitoringScheduleResponse,
    summary="[Phase 20] Run a monitoring schedule immediately",
)
def trigger_schedule(
    schedule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonitoringScheduleResponse:
    """Manually trigger immediate execution of a schedule."""
    schedule = monitoring_service.trigger_schedule_now(
        db=db,
        schedule_id=schedule_id,
        user_id=current_user.id,
    )
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitoring schedule not found.",
        )
    return MonitoringScheduleResponse.model_validate(schedule)


# ---------------------------------------------------------------------------
# Notification Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/notifications",
    response_model=NotificationListResponse,
    summary="[Phase 20] List user notifications",
)
def list_notifications(
    is_read: bool | None = Query(default=None, description="Filter by read status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationListResponse:
    """List in-app notifications for the authenticated user."""
    notifications, total, unread = monitoring_service.list_notifications(
        db=db,
        user_id=current_user.id,
        is_read=is_read,
        limit=limit,
        offset=offset,
    )
    return NotificationListResponse(
        notifications=[NotificationResponse.model_validate(n) for n in notifications],
        total_count=total,
        unread_count=unread,
    )


@router.get(
    "/notifications/unread-count",
    response_model=UnreadCountResponse,
    summary="[Phase 20] Get unread notification count",
)
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnreadCountResponse:
    """Return count of unread notifications for badge display."""
    unread = monitoring_service.get_unread_count(db=db, user_id=current_user.id)
    return UnreadCountResponse(unread_count=unread)


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    summary="[Phase 20] Mark notification as read",
)
def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationResponse:
    """Mark a specific notification as read."""
    notification = monitoring_service.mark_as_read(
        db=db,
        notification_id=notification_id,
        user_id=current_user.id,
    )
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    return NotificationResponse.model_validate(notification)


@router.post(
    "/notifications/mark-all-read",
    response_model=MarkReadResponse,
    summary="[Phase 20] Mark all notifications as read",
)
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkReadResponse:
    """Mark all unread notifications for the authenticated user as read."""
    count = monitoring_service.mark_all_as_read(db=db, user_id=current_user.id)
    return MarkReadResponse(success=True, marked_count=count)


@router.delete(
    "/notifications/{notification_id}",
    status_code=status.HTTP_200_OK,
    summary="[Phase 20] Delete a notification",
)
def delete_notification(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete a notification owned by the authenticated user."""
    deleted = monitoring_service.delete_notification(
        db=db,
        notification_id=notification_id,
        user_id=current_user.id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    return {"message": "Notification deleted successfully."}
