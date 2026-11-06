"""
Phase 7 verification tests: Heartbeat monitor lifecycle, peer failure detection,
and offline state transitions.
"""

from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.node import Node
from app.models.node_peer import NodePeer
from app.services.heartbeat_service import HeartbeatService
from app.services.node_service import NodeService


@pytest.mark.asyncio
async def test_heartbeat_lifecycle():
    """Verify HeartbeatService can start and stop safely."""
    HeartbeatService.start(interval_seconds=1)
    assert HeartbeatService._running is True
    assert HeartbeatService._task is not None

    await HeartbeatService.stop()
    assert HeartbeatService._running is False
    assert HeartbeatService._task is None


@pytest.mark.asyncio
async def test_heartbeat_peer_failure_detection(test_session: AsyncSession):
    """Verify unresponsive peers are flagged DISCONNECTED and OFFLINE by heartbeat check."""
    await NodeService.init_or_update_local_node(test_session)

    # Register an unresponsive peer pointing to a dead port
    dead_peer_node = Node(
        nodeId="myc-node-dead",
        nodeType="FULL",
        endpoint="http://127.0.0.1:59999",
        status="ONLINE",
        protocolVersion="v1.0.0",
        p2pPublicKey="04" + "9" * 128,
        lastHeartbeat=datetime.now(timezone.utc),
    )
    test_session.add(dead_peer_node)

    dead_peer_rel = NodePeer(
        localNodeId=settings.NODE_ID,
        peerNodeId="myc-node-dead",
        status="CONNECTED",
        lastConnectedAt=datetime.now(timezone.utc),
    )
    test_session.add(dead_peer_rel)
    await test_session.commit()

    # Run health check pass
    await HeartbeatService.check_peers_and_update_self()

    # Re-query
    peer_res = await test_session.execute(
        select(NodePeer).where(NodePeer.peerNodeId == "myc-node-dead")
    )
    updated_peer = peer_res.scalar_one()
    assert updated_peer.status == "DISCONNECTED"

    node_res = await test_session.execute(
        select(Node).where(Node.nodeId == "myc-node-dead")
    )
    updated_node = node_res.scalar_one()
    assert updated_node.status == "OFFLINE"

