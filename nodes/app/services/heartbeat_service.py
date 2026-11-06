"""
Background heartbeat service for peer health monitoring, failure detection, and auto-reconnection.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Optional
import httpx
from sqlalchemy import select

from app.core.config import settings
from app.database.session import AsyncSessionLocal
from app.models.node import Node
from app.models.node_peer import NodePeer
from app.services.node_service import NodeService

logger = logging.getLogger("myc_node.service.heartbeat")


class HeartbeatService:
    """Manages periodic peer health monitoring and network status."""

    _task: Optional[asyncio.Task] = None
    _running: bool = False

    @classmethod
    def start(cls, interval_seconds: int = 5) -> None:
        """Start the background heartbeat monitor task."""
        if cls._running:
            return
        cls._running = True
        cls._task = asyncio.create_task(cls._heartbeat_loop(interval_seconds))
        logger.info(
            "Node %s heartbeat monitor started (interval=%ds)",
            settings.NODE_ID,
            interval_seconds,
        )

    @classmethod
    async def stop(cls) -> None:
        """Gracefully stop the background heartbeat monitor."""
        cls._running = False
        if cls._task and not cls._task.done():
            cls._task.cancel()
            try:
                await cls._task
            except asyncio.CancelledError:
                pass
        cls._task = None
        logger.info("Node %s heartbeat monitor stopped", settings.NODE_ID)

    @classmethod
    async def _heartbeat_loop(cls, interval_seconds: int) -> None:
        """Infinite loop periodically executing peer health checks."""
        while cls._running:
            try:
                await cls.check_peers_and_update_self()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in heartbeat loop: %s", exc)

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    @classmethod
    async def check_peers_and_update_self(cls) -> None:
        """
        1. Refreshes local node's own heartbeat in database.
        2. Probes all tracked peers via HTTP health endpoint.
        3. Marks unresponsive peers as DISCONNECTED and OFFLINE.
        4. Restores responding peers to CONNECTED and ONLINE.
        """
        async with AsyncSessionLocal() as session:
            # 1. Update self heartbeat
            await NodeService.update_heartbeat(session)

            # 2. Query all peers for local node
            stmt = select(NodePeer).where(NodePeer.localNodeId == settings.NODE_ID)
            res = await session.execute(stmt)
            peers = res.scalars().all()

            for peer in peers:
                node_res = await session.execute(
                    select(Node).where(Node.nodeId == peer.peerNodeId)
                )
                peer_node = node_res.scalar_one_or_none()
                if not peer_node or not peer_node.endpoint:
                    continue

                endpoint = peer_node.endpoint.rstrip("/")
                now = datetime.now(timezone.utc)
                is_reachable = False

                try:
                    async with httpx.AsyncClient(timeout=settings.PEER_TIMEOUT_SECONDS) as client:
                        resp = await client.get(
                            f"{endpoint}/api/v1/node/health",
                            headers={"X-Network-Key": settings.NETWORK_KEY},
                        )
                        if resp.status_code == 200:
                            is_reachable = True
                except Exception:
                    is_reachable = False

                if is_reachable:
                    if peer.status != "CONNECTED":
                        logger.info("Peer %s reconnected to %s", peer.peerNodeId, settings.NODE_ID)
                    peer.status = "CONNECTED"
                    peer.lastConnectedAt = now
                    peer_node.status = "ONLINE"
                    peer_node.lastHeartbeat = now
                else:
                    if peer.status == "CONNECTED":
                        logger.warning(
                            "Peer %s on %s is unresponsive; marking DISCONNECTED",
                            peer.peerNodeId,
                            endpoint,
                        )
                    peer.status = "DISCONNECTED"
                    peer_node.status = "OFFLINE"

            await session.commit()

