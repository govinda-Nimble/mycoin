"""
Node service managing local node identity, status lifecycle, and heartbeat.
"""

from datetime import datetime, timezone
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.node import Node
from app.schemas.node import NodeInfoResponse

logger = logging.getLogger("myc_node.service")


class NodeService:
    """Service handling local node lifecycle and persistence."""

    @staticmethod
    async def get_local_node(db: AsyncSession) -> Optional[Node]:
        """Fetch the local node record from the node's isolated database."""
        stmt = select(Node).where(Node.nodeId == settings.NODE_ID)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def init_or_update_local_node(db: AsyncSession) -> Node:
        """
        Self-registers or updates the local node record in its own database upon startup.
        Ensures the node is marked ONLINE and its endpoint / credentials are up to date.
        """
        node = await NodeService.get_local_node(db)
        now = datetime.now(timezone.utc)

        if node is None:
            logger.info("Local node record not found. Initializing node %s in database...", settings.NODE_ID)
            node = Node(
                nodeId=settings.NODE_ID,
                nodeType=settings.NODE_TYPE,
                endpoint=settings.ENDPOINT,
                status="ONLINE",
                protocolVersion=settings.PROTOCOL_VERSION,
                p2pPublicKey=settings.P2P_PUBLIC_KEY,
                lastHeartbeat=now,
            )
            db.add(node)
        else:
            logger.info("Updating existing local node %s in database...", settings.NODE_ID)
            node.nodeType = settings.NODE_TYPE
            node.endpoint = settings.ENDPOINT
            node.status = "ONLINE"
            node.protocolVersion = settings.PROTOCOL_VERSION
            node.p2pPublicKey = settings.P2P_PUBLIC_KEY
            node.lastHeartbeat = now

        await db.commit()
        await db.refresh(node)
        logger.info("Local node %s initialized with status %s", node.nodeId, node.status)
        return node

    @staticmethod
    async def update_heartbeat(db: AsyncSession) -> Optional[Node]:
        """Update local node heartbeat timestamp and ensure status is ONLINE."""
        node = await NodeService.get_local_node(db)
        if node:
            node.lastHeartbeat = datetime.now(timezone.utc)
            node.status = "ONLINE"
            await db.commit()
            await db.refresh(node)
        return node

    @staticmethod
    async def set_node_offline(db: AsyncSession) -> None:
        """Mark the local node as OFFLINE upon graceful shutdown."""
        node = await NodeService.get_local_node(db)
        if node:
            node.status = "OFFLINE"
            await db.commit()
            logger.info("Local node %s marked as OFFLINE", settings.NODE_ID)

    @staticmethod
    async def get_node_info(db: AsyncSession) -> NodeInfoResponse:
        """
        Produce a comprehensive NodeInfoResponse combining database state
        with network parameters (e.g. chainId).
        """
        node = await NodeService.get_local_node(db)
        if node:
            return NodeInfoResponse(
                id=node.id,
                nodeId=node.nodeId,
                nodeType=node.nodeType,
                endpoint=node.endpoint,
                status=node.status,
                protocolVersion=node.protocolVersion,
                p2pPublicKey=node.p2pPublicKey,
                chainId=settings.CHAIN_ID,
                lastHeartbeat=node.lastHeartbeat,
                createdAt=node.createdAt,
                updatedAt=node.updatedAt,
            )

        # Fallback to in-memory settings if database record not yet committed
        return NodeInfoResponse(
            id=None,
            nodeId=settings.NODE_ID,
            nodeType=settings.NODE_TYPE,
            endpoint=settings.ENDPOINT,
            status="ONLINE",
            protocolVersion=settings.PROTOCOL_VERSION,
            p2pPublicKey=settings.P2P_PUBLIC_KEY,
            chainId=settings.CHAIN_ID,
            lastHeartbeat=datetime.now(timezone.utc),
            createdAt=None,
            updatedAt=None,
        )

