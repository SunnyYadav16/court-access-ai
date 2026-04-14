"""
api/tests/test_health.py

Tests for health and root meta-endpoints.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_body_status_ok(client: AsyncClient) -> None:
    data = (await client.get("/health")).json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_health_body_has_version(client: AsyncClient) -> None:
    data = (await client.get("/health")).json()
    assert "version" in data
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_body_has_environment(client: AsyncClient) -> None:
    data = (await client.get("/health")).json()
    assert "environment" in data
    assert data["environment"] == "test"


@pytest.mark.asyncio
async def test_root_returns_200(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_root_body_has_name(client: AsyncClient) -> None:
    data = (await client.get("/")).json()
    assert "name" in data
    assert "CourtAccess" in data["name"]
