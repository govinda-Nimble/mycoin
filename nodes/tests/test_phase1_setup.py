"""
Phase 1 verification tests.
Tests settings configuration, FastAPI application startup, and health check endpoints.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import app


@pytest.mark.asyncio
async def test_settings_defaults():
    """Verify default configuration values."""
    custom_settings = Settings(NODE_ID="test-node-99", PORT=8999)
    assert custom_settings.NODE_ID == "test-node-99"
    assert custom_settings.PORT == 8999
    assert custom_settings.CHAIN_ID == 1001
    assert custom_settings.PROTOCOL_VERSION == "v1.0.0"


@pytest.mark.asyncio
async def test_root_endpoint():
    """Verify root status endpoint returns valid node information."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "nodeId" in data
        assert "chainId" in data
        assert data["chainId"] == 1001


@pytest.mark.asyncio
async def test_health_endpoint():
    """Verify health check returns healthy status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "protocolVersion" in data

