"""
Phase 2 verification tests: Node model, initialization service, and node API routes.
"""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.node import Node
from app.services.node_service import NodeService


@pytest.mark.asyncio
async def test_node_model_creation(test_session: AsyncSession):
    """Verify Node model persistence and schema integrity."""
    node = Node(
        nodeId="myc-node-test-01",
        nodeType="FULL",
        endpoint="http://localhost:8999",
        status="ONLINE",
        protocolVersion="v1.0.0",
        p2pPublicKey="04" + "a" * 128,
        lastHeartbeat=datetime.now(timezone.utc),
    )
    test_session.add(node)
    await test_session.commit()
    await test_session.refresh(node)

    assert node.id is not None
    assert node.nodeId == "myc-node-test-01"
    assert node.status == "ONLINE"
    assert node.createdAt is not None
    assert node.updatedAt is not None


@pytest.mark.asyncio
async def test_node_service_initialization_and_update(test_session: AsyncSession):
    """Verify NodeService creates local node and updates idempotently."""
    # 1. First initialization: should create record
    node1 = await NodeService.init_or_update_local_node(test_session)
    assert node1.nodeId == settings.NODE_ID
    assert node1.status == "ONLINE"
    assert node1.endpoint == settings.ENDPOINT

    # 2. Re-running should update rather than duplicate
    node2 = await NodeService.init_or_update_local_node(test_session)
    assert node2.id == node1.id
    assert node2.nodeId == settings.NODE_ID

    # Verify only one record exists in database
    result = await test_session.execute(select(Node).where(Node.nodeId == settings.NODE_ID))
    nodes = result.scalars().all()
    assert len(nodes) == 1


@pytest.mark.asyncio
async def test_node_service_heartbeat_and_offline(test_session: AsyncSession):
    """Verify heartbeat update and offline transition."""
    await NodeService.init_or_update_local_node(test_session)

    # Heartbeat
    updated = await NodeService.update_heartbeat(test_session)
    assert updated is not None
    assert updated.status == "ONLINE"
    assert updated.lastHeartbeat is not None

    # Offline transition
    await NodeService.set_node_offline(test_session)
    local_node = await NodeService.get_local_node(test_session)
    assert local_node is not None
    assert local_node.status == "OFFLINE"


@pytest.mark.asyncio
async def test_get_node_info_endpoint(test_client: AsyncClient, test_session: AsyncSession):
    """Verify GET /api/v1/node/info returns comprehensive node metadata."""
    await NodeService.init_or_update_local_node(test_session)

    response = await test_client.get("/api/v1/node/info")
    assert response.status_code == 200

    data = response.json()
    assert data["nodeId"] == settings.NODE_ID
    assert data["nodeType"] == settings.NODE_TYPE
    assert data["endpoint"] == settings.ENDPOINT
    assert data["status"] == "ONLINE"
    assert data["protocolVersion"] == settings.PROTOCOL_VERSION
    assert data["chainId"] == settings.CHAIN_ID
    assert "p2pPublicKey" in data


@pytest.mark.asyncio
async def test_get_node_health_endpoint(test_client: AsyncClient, test_session: AsyncSession):
    """Verify GET /api/v1/node/health diagnostics return database connectivity and metrics."""
    await NodeService.init_or_update_local_node(test_session)

    response = await test_client.get("/api/v1/node/health")
    assert response.status_code == 200

    data = response.json()
    assert data["nodeId"] == settings.NODE_ID
    assert data["status"] == "ONLINE"
    assert data["database"] == "connected"
    assert data["endpoint"] == settings.ENDPOINT
    assert data["connectedPeersCount"] == 0
    assert data["mempoolSize"] == 0
    assert data["latestBlockHeight"] == 0
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_post_node_heartbeat_endpoint(test_client: AsyncClient, test_session: AsyncSession):
    """Verify POST /api/v1/node/heartbeat successfully refreshes node activity."""
    await NodeService.init_or_update_local_node(test_session)

    response = await test_client.post("/api/v1/node/heartbeat")
    assert response.status_code == 200

    data = response.json()
    assert data["message"] == "Heartbeat updated successfully"
    assert data["nodeId"] == settings.NODE_ID
    assert data["status"] == "ONLINE"
    assert "lastHeartbeat" in data

