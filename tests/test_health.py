"""Tests for the health API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /api/health should return HTTP 200 with status 'ok'."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.anyio
async def test_health_response_shape(client: AsyncClient) -> None:
    """GET /api/health response should match the HealthResponse schema."""
    response = await client.get("/api/health")
    data = response.json()
    assert set(data.keys()) == {"status"}


@pytest.mark.anyio
async def test_db_health_returns_200(client: AsyncClient) -> None:
    """GET /api/health/db should return HTTP 200 regardless of DB state.

    In test environments the database may not be available,
    so we only verify the endpoint responds correctly.
    """
    response = await client.get("/api/health/db")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert data["database"] in ("connected", "disconnected")


@pytest.mark.anyio
async def test_db_health_response_shape(client: AsyncClient) -> None:
    """GET /api/health/db response should match the DBHealthResponse schema."""
    response = await client.get("/api/health/db")
    data = response.json()
    assert set(data.keys()) == {"status", "database"}


@pytest.mark.anyio
async def test_nonexistent_route_returns_404(client: AsyncClient) -> None:
    """Unknown routes should return 404, not 500."""
    response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
