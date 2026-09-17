"""Health check API endpoints."""

from fastapi import APIRouter

from app.db.session import check_db_connection
from app.schemas.health import DBHealthResponse, HealthResponse

router = APIRouter(prefix="/api/health", tags=["Health"])


@router.get(
    "",
    response_model=HealthResponse,
    summary="Application health check",
    description="Returns OK if the API server is running.",
)
async def health() -> HealthResponse:
    """Simple liveness check — no dependencies required."""
    return HealthResponse(status="ok")


@router.get(
    "/db",
    response_model=DBHealthResponse,
    summary="Database connectivity check",
    description="Verifies that the backend can reach PostgreSQL.",
)
async def health_db() -> DBHealthResponse:
    """Check database connectivity via SELECT 1."""
    connected = check_db_connection()
    if connected:
        return DBHealthResponse(status="ok", database="connected")
    return DBHealthResponse(status="degraded", database="disconnected")
