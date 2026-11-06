"""
Peer service managing discovery, handshakes, connections, and peer health pings.
"""

from datetime import datetime, timezone
import logging
import time
from typing import Optional
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.node import Node
from app.models.node_peer import NodePeer
from app.schemas.peer import (
    PeerHandshakeRequest,
    PeerListResponse,
    PeerResponse,
    PingResponse,
)

logger = logging.getLogger("myc_node.service.peer")


class PeerService:
    """Service handling P2P connections, handshakes, and peer status."""

    @staticmethod
    async def connect_to_peer(db: AsyncSession, peer_endpoint: str) -> PeerResponse:
        """
        Initiate an outbound connection to a target peer node endpoint.
        Validates remote chainId, prevents self-peering, records peer locally,
        and triggers a bidirectional handshake with the remote peer.
        """
        clean_endpoint = peer_endpoint.rstrip("/")
        if clean_endpoint == settings.ENDPOINT.rstrip("/"):
            raise ValueError("Cannot peer with self (endpoint matches local node endpoint)")

        logger.info("Attempting connection from %s to peer at %s", settings.NODE_ID, clean_endpoint)

        # 1. Fetch remote node info
        try:
            async with httpx.AsyncClient(timeout=settings.PEER_TIMEOUT_SECONDS) as client:
                res = await client.get(
                    f"{clean_endpoint}/api/v1/node/info",
                    headers={"X-Network-Key": settings.NETWORK_KEY},
                )
                if res.status_code != 200:
                    raise RuntimeError(f"Peer returned HTTP {res.status_code}: {res.text}")
                peer_data = res.json()
        except Exception as exc:
            logger.error("Failed to connect to peer at %s: %s", clean_endpoint, exc)
            raise RuntimeError(f"Unable to reach peer at {clean_endpoint}: {str(exc)}") from exc

        remote_node_id = peer_data.get("nodeId")
        remote_chain_id = peer_data.get("chainId")
        remote_pubkey = peer_data.get("p2pPublicKey", "")
        remote_type = peer_data.get("nodeType", "FULL")
        remote_version = peer_data.get("protocolVersion", "v1.0.0")

        # 2. Validation
        if remote_node_id == settings.NODE_ID:
            raise ValueError(f"Cannot peer with self: target node ID '{remote_node_id}' equals local node ID")

        if remote_chain_id != settings.CHAIN_ID:
            raise ValueError(
                f"Chain ID mismatch: local network is {settings.CHAIN_ID}, peer belongs to {remote_chain_id}"
            )

        now = datetime.now(timezone.utc)

        # 3. Save or update remote node details in local nodes cache
        node_stmt = select(Node).where(Node.nodeId == remote_node_id)
        node_res = await db.execute(node_stmt)
        cached_node = node_res.scalar_one_or_none()

        if cached_node is None:
            cached_node = Node(
                nodeId=remote_node_id,
                nodeType=remote_type,
                endpoint=clean_endpoint,
                status="ONLINE",
                protocolVersion=remote_version,
                p2pPublicKey=remote_pubkey,
                lastHeartbeat=now,
            )
            db.add(cached_node)
        else:
            cached_node.endpoint = clean_endpoint
            cached_node.status = "ONLINE"
            cached_node.protocolVersion = remote_version
            cached_node.p2pPublicKey = remote_pubkey
            cached_node.lastHeartbeat = now

        # 4. Save or update peer relationship in local node_peers
        peer_stmt = select(NodePeer).where(
            NodePeer.localNodeId == settings.NODE_ID,
            NodePeer.peerNodeId == remote_node_id,
        )
        peer_res = await db.execute(peer_stmt)
        peer_rel = peer_res.scalar_one_or_none()

        if peer_rel is None:
            peer_rel = NodePeer(
                localNodeId=settings.NODE_ID,
                peerNodeId=remote_node_id,
                status="CONNECTED",
                lastConnectedAt=now,
            )
            db.add(peer_rel)
        else:
            peer_rel.status = "CONNECTED"
            peer_rel.lastConnectedAt = now

        await db.commit()
        await db.refresh(peer_rel)

        # 5. Notify remote peer via handshake to establish bidirectional connection
        try:
            handshake_payload = {
                "nodeId": settings.NODE_ID,
                "nodeType": settings.NODE_TYPE,
                "endpoint": settings.ENDPOINT,
                "protocolVersion": settings.PROTOCOL_VERSION,
                "chainId": settings.CHAIN_ID,
                "p2pPublicKey": settings.P2P_PUBLIC_KEY,
            }
            async with httpx.AsyncClient(timeout=settings.PEER_TIMEOUT_SECONDS) as client:
                await client.post(
                    f"{clean_endpoint}/api/v1/peers/handshake",
                    json=handshake_payload,
                    headers={"X-Network-Key": settings.NETWORK_KEY},
                )
                logger.info("Bidirectional handshake completed with %s (%s)", remote_node_id, clean_endpoint)
        except Exception as exc:
            logger.warning("Remote handshake notification to %s failed: %s", clean_endpoint, exc)

        return PeerResponse(
            id=peer_rel.id,
            localNodeId=peer_rel.localNodeId,
            peerNodeId=peer_rel.peerNodeId,
            endpoint=clean_endpoint,
            status=peer_rel.status,
            lastConnectedAt=peer_rel.lastConnectedAt,
            createdAt=peer_rel.createdAt,
            updatedAt=peer_rel.updatedAt,
        )

    @staticmethod
    async def handle_handshake(db: AsyncSession, handshake: PeerHandshakeRequest) -> PeerResponse:
        """
        Handle incoming peer handshake from another node wanting to connect.
        Registers the sender in local nodes and marks the peer relationship as CONNECTED.
        """
        if handshake.nodeId == settings.NODE_ID:
            raise ValueError("Cannot peer with self")

        if handshake.chainId != settings.CHAIN_ID:
            raise ValueError(f"Chain ID mismatch: expected {settings.CHAIN_ID}, got {handshake.chainId}")

        clean_endpoint = handshake.endpoint.rstrip("/")
        now = datetime.now(timezone.utc)

        # Upsert into nodes table
        node_stmt = select(Node).where(Node.nodeId == handshake.nodeId)
        node_res = await db.execute(node_stmt)
        cached_node = node_res.scalar_one_or_none()

        if cached_node is None:
            cached_node = Node(
                nodeId=handshake.nodeId,
                nodeType=handshake.nodeType,
                endpoint=clean_endpoint,
                status="ONLINE",
                protocolVersion=handshake.protocolVersion,
                p2pPublicKey=handshake.p2pPublicKey,
                lastHeartbeat=now,
            )
            db.add(cached_node)
        else:
            cached_node.endpoint = clean_endpoint
            cached_node.status = "ONLINE"
            cached_node.protocolVersion = handshake.protocolVersion
            cached_node.p2pPublicKey = handshake.p2pPublicKey
            cached_node.lastHeartbeat = now

        # Upsert into node_peers table
        peer_stmt = select(NodePeer).where(
            NodePeer.localNodeId == settings.NODE_ID,
            NodePeer.peerNodeId == handshake.nodeId,
        )
        peer_res = await db.execute(peer_stmt)
        peer_rel = peer_res.scalar_one_or_none()

        if peer_rel is None:
            peer_rel = NodePeer(
                localNodeId=settings.NODE_ID,
                peerNodeId=handshake.nodeId,
                status="CONNECTED",
                lastConnectedAt=now,
            )
            db.add(peer_rel)
        else:
            peer_rel.status = "CONNECTED"
            peer_rel.lastConnectedAt = now

        await db.commit()
        await db.refresh(peer_rel)

        logger.info("Handshake accepted from node %s (%s)", handshake.nodeId, clean_endpoint)

        return PeerResponse(
            id=peer_rel.id,
            localNodeId=peer_rel.localNodeId,
            peerNodeId=peer_rel.peerNodeId,
            endpoint=clean_endpoint,
            status=peer_rel.status,
            lastConnectedAt=peer_rel.lastConnectedAt,
            createdAt=peer_rel.createdAt,
            updatedAt=peer_rel.updatedAt,
        )

    @staticmethod
    async def list_peers(db: AsyncSession) -> PeerListResponse:
        """Fetch all peer records for the local node with endpoints."""
        stmt = select(NodePeer).where(NodePeer.localNodeId == settings.NODE_ID)
        result = await db.execute(stmt)
        peers = result.scalars().all()

        peer_items = []
        connected_count = 0

        for p in peers:
            # Retrieve endpoint from nodes table
            node_res = await db.execute(select(Node).where(Node.nodeId == p.peerNodeId))
            node_record = node_res.scalar_one_or_none()
            endpoint = node_record.endpoint if node_record else None

            if p.status == "CONNECTED":
                connected_count += 1

            peer_items.append(
                PeerResponse(
                    id=p.id,
                    localNodeId=p.localNodeId,
                    peerNodeId=p.peerNodeId,
                    endpoint=endpoint,
                    status=p.status,
                    lastConnectedAt=p.lastConnectedAt,
                    createdAt=p.createdAt,
                    updatedAt=p.updatedAt,
                )
            )

        return PeerListResponse(
            totalCount=len(peer_items),
            connectedCount=connected_count,
            peers=peer_items,
        )

    @staticmethod
    async def disconnect_peer(db: AsyncSession, peer_node_id: str) -> bool:
        """Mark a peer as DISCONNECTED."""
        stmt = select(NodePeer).where(
            NodePeer.localNodeId == settings.NODE_ID,
            NodePeer.peerNodeId == peer_node_id,
        )
        result = await db.execute(stmt)
        peer = result.scalar_one_or_none()
        if not peer:
            return False

        peer.status = "DISCONNECTED"
        await db.commit()
        logger.info("Peer %s disconnected from %s", peer_node_id, settings.NODE_ID)
        return True

    @staticmethod
    async def ping_peer(db: AsyncSession, peer_node_id: str) -> PingResponse:
        """Ping a remote peer endpoint and record network latency."""
        node_res = await db.execute(select(Node).where(Node.nodeId == peer_node_id))
        node_record = node_res.scalar_one_or_none()
        if not node_record:
            raise ValueError(f"Peer '{peer_node_id}' is not in known nodes database")

        start_time = time.perf_counter()
        async with httpx.AsyncClient(timeout=settings.PEER_TIMEOUT_SECONDS) as client:
            res = await client.get(
                f"{node_record.endpoint}/api/v1/node/health",
                headers={"X-Network-Key": settings.NETWORK_KEY},
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if res.status_code != 200:
                raise RuntimeError(f"Ping returned HTTP {res.status_code}")

        # Update lastConnectedAt
        peer_stmt = select(NodePeer).where(
            NodePeer.localNodeId == settings.NODE_ID,
            NodePeer.peerNodeId == peer_node_id,
        )
        peer_res = await db.execute(peer_stmt)
        peer_rel = peer_res.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if peer_rel:
            peer_rel.lastConnectedAt = now
            peer_rel.status = "CONNECTED"
            await db.commit()

        return PingResponse(
            peerNodeId=peer_node_id,
            endpoint=node_record.endpoint,
            status="CONNECTED",
            latencyMs=round(elapsed_ms, 2),
            timestamp=now,
        )

