"""
Phase 3 verification tests: NodePeer model, peer handshake, discovery, and peer endpoints.
"""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.node_peer import NodePeer
from app.schemas.peer import PeerHandshakeRequest
from app.services.node_service import NodeService
from app.services.peer_service import PeerService


@pytest.mark.asyncio
async def test_node_peer_model(test_session: AsyncSession):
    """Verify NodePeer model persistence and constraints."""
    peer = NodePeer(
        localNodeId=settings.NODE_ID,
        peerNodeId="myc-node-002",
        status="CONNECTED",
        lastConnectedAt=datetime.now(timezone.utc),
    )
    test_session.add(peer)
    await test_session.commit()
    await test_session.refresh(peer)

    assert peer.id is not None
    assert peer.localNodeId == settings.NODE_ID
    assert peer.peerNodeId == "myc-node-002"
    assert peer.status == "CONNECTED"


@pytest.mark.asyncio
async def test_peer_handshake_service(test_session: AsyncSession):
    """Verify incoming handshake registers peer and remote node record."""
    await NodeService.init_or_update_local_node(test_session)

    handshake_req = PeerHandshakeRequest(
        nodeId="myc-node-002",
        nodeType="FULL",
        endpoint="http://localhost:8002",
        protocolVersion="v1.0.0",
        chainId=settings.CHAIN_ID,
        p2pPublicKey="04" + "b" * 128,
    )

    response = await PeerService.handle_handshake(test_session, handshake_req)
    assert response.localNodeId == settings.NODE_ID
    assert response.peerNodeId == "myc-node-002"
    assert response.endpoint == "http://localhost:8002"
    assert response.status == "CONNECTED"

    # Self-peering rejection
    self_handshake = PeerHandshakeRequest(
        nodeId=settings.NODE_ID,
        nodeType="FULL",
        endpoint=settings.ENDPOINT,
        protocolVersion="v1.0.0",
        chainId=settings.CHAIN_ID,
        p2pPublicKey="04" + "a" * 128,
    )
    with pytest.raises(ValueError, match="Cannot peer with self"):
        await PeerService.handle_handshake(test_session, self_handshake)

    # Chain ID mismatch rejection
    mismatch_handshake = PeerHandshakeRequest(
        nodeId="myc-node-999",
        nodeType="FULL",
        endpoint="http://localhost:9999",
        protocolVersion="v1.0.0",
        chainId=99999,
        p2pPublicKey="04" + "c" * 128,
    )
    with pytest.raises(ValueError, match="Chain ID mismatch"):
        await PeerService.handle_handshake(test_session, mismatch_handshake)


@pytest.mark.asyncio
async def test_peer_list_and_disconnect_service(test_session: AsyncSession):
    """Verify peer listing and graceful disconnection."""
    await NodeService.init_or_update_local_node(test_session)

    handshake_req = PeerHandshakeRequest(
        nodeId="myc-node-003",
        nodeType="VALIDATOR",
        endpoint="http://localhost:8003",
        protocolVersion="v1.0.0",
        chainId=settings.CHAIN_ID,
        p2pPublicKey="04" + "d" * 128,
    )
    await PeerService.handle_handshake(test_session, handshake_req)

    # List peers
    peer_list = await PeerService.list_peers(test_session)
    assert peer_list.totalCount >= 1
    assert peer_list.connectedCount >= 1
    assert any(p.peerNodeId == "myc-node-003" for p in peer_list.peers)

    # Disconnect peer
    disconnected = await PeerService.disconnect_peer(test_session, "myc-node-003")
    assert disconnected is True

    # Verify status changed
    peer_list_after = await PeerService.list_peers(test_session)
    peer_record = next(p for p in peer_list_after.peers if p.peerNodeId == "myc-node-003")
    assert peer_record.status == "DISCONNECTED"


@pytest.mark.asyncio
async def test_peer_api_endpoints(test_client: AsyncClient, test_session: AsyncSession):
    """Verify peer HTTP API routes: handshake, list, disconnect, health metrics."""
    await NodeService.init_or_update_local_node(test_session)

    # 1. Handshake API with network authentication header
    handshake_payload = {
        "nodeId": "myc-node-002",
        "nodeType": "FULL",
        "endpoint": "http://localhost:8002",
        "protocolVersion": "v1.0.0",
        "chainId": settings.CHAIN_ID,
        "p2pPublicKey": "04" + "b" * 128,
    }
    handshake_res = await test_client.post(
        "/api/v1/peers/handshake",
        json=handshake_payload,
        headers={"X-Network-Key": settings.NETWORK_KEY},
    )
    assert handshake_res.status_code == 200
    assert handshake_res.json()["peerNodeId"] == "myc-node-002"

    # 2. Peer List API
    list_res = await test_client.get("/api/v1/peers")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["totalCount"] == 1
    assert list_data["connectedCount"] == 1

    # 3. Node health endpoint reflects connected peer count
    health_res = await test_client.get("/api/v1/node/health")
    assert health_res.status_code == 200
    assert health_res.json()["connectedPeersCount"] == 1

    # 4. Disconnect API
    disconnect_res = await test_client.delete("/api/v1/peers/myc-node-002")
    assert disconnect_res.status_code == 200
    assert disconnect_res.json()["status"] == "DISCONNECTED"

    # 5. Node health reflects 0 connected peers after disconnect
    health_res2 = await test_client.get("/api/v1/node/health")
    assert health_res2.status_code == 200
    assert health_res2.json()["connectedPeersCount"] == 0

