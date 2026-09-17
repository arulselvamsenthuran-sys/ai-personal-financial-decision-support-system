"""Pydantic response schemas for the health endpoints."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response for GET /api/health."""

    status: str


class DBHealthResponse(BaseModel):
    """Response for GET /api/health/db."""

    status: str
    database: str
