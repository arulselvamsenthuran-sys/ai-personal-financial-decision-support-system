"""Phase 20 — Monitoring and Notification Pydantic Schemas.

Request / Response models for recurring financial-monitoring schedules
and in-app notifications.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Monitoring Schedule Schemas
# ---------------------------------------------------------------------------

FrequencyType = Literal["DAILY", "WEEKLY"]


class MonitoringScheduleCreate(BaseModel):
    """Payload to create a new monitoring schedule."""

    name: str = Field(..., min_length=1, max_length=200, description="Schedule name")
    frequency: FrequencyType = Field(..., description="Schedule frequency (DAILY or WEEKLY)")
    day_of_week: int | None = Field(
        default=None,
        ge=1,
        le=7,
        description="Day of week (1=Monday ... 7=Sunday). Required for WEEKLY.",
    )
    hour_of_day: int = Field(
        default=8,
        ge=0,
        le=23,
        description="Hour of day in UTC (0-23).",
    )
    is_enabled: bool = Field(default=True, description="Whether schedule is active.")

    @model_validator(mode="after")
    def validate_weekly_day_of_week(self) -> Self:
        if self.frequency == "WEEKLY" and self.day_of_week is None:
            raise ValueError("day_of_week is required when frequency is WEEKLY (1=Mon ... 7=Sun).")
        return self



class MonitoringScheduleUpdate(BaseModel):
    """Payload to update an existing monitoring schedule."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    frequency: FrequencyType | None = None
    day_of_week: int | None = Field(default=None, ge=1, le=7)
    hour_of_day: int | None = Field(default=None, ge=0, le=23)
    is_enabled: bool | None = None


class MonitoringScheduleResponse(BaseModel):
    """Response representation of a monitoring schedule."""

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    frequency: str
    day_of_week: int | None
    hour_of_day: int
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None
    next_run_at: datetime | None

    model_config = {"from_attributes": True}


class MonitoringScheduleListResponse(BaseModel):
    """List of schedules for authenticated user."""

    schedules: list[MonitoringScheduleResponse]
    total_count: int


# ---------------------------------------------------------------------------
# Notification Schemas
# ---------------------------------------------------------------------------

class NotificationResponse(BaseModel):
    """Representation of an in-app notification."""

    id: uuid.UUID
    user_id: uuid.UUID
    schedule_id: uuid.UUID | None
    notification_type: str
    title: str
    body: str
    is_read: bool
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    """Paginated list of notifications for authenticated user."""

    notifications: list[NotificationResponse]
    total_count: int
    unread_count: int


class UnreadCountResponse(BaseModel):
    """Summary of unread notifications count."""

    unread_count: int


class MarkReadResponse(BaseModel):
    """Confirmation of marking notifications as read."""

    success: bool
    marked_count: int
