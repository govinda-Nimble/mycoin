"""
Node information and status API endpoints.
"""

from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.config import settings
from app.models.node_peer import NodePeer
from app.schemas.node import NodeHealthResponse, NodeInfoResponse
from app.services.mempool_service import MempoolService
from app.services.node_service import NodeService

logger = logging.getLogger("myc_node.api.node")

router = APIRouter(prefix="/node", tags=["Node Information"])


@router.get(
    "/info",
    response_model=NodeInfoResponse,
    summary="Get Local Node Information",
    description="Returns identity, endpoint, status, and network configuration of this independent node.",
)
async def get_node_info(
    db: AsyncSession = Depends(get_db),
) -> NodeInfoResponse:
    """Retrieve identity and status of the current node."""
    return await NodeService.get_node_info(db)


@router.get(
    "/health",
    response_model=NodeHealthResponse,
    summary="Get Detailed Node Health Diagnostics",
    description="Performs database connectivity checks and returns operational metrics.",
)
async def get_node_health(
    db: AsyncSession = Depends(get_db),
) -> NodeHealthResponse:
    """Check node database connectivity and operational parameters."""
    db_status = "connected"
    connected_peers_count = 0
    mempool_size = 0

    try:
        await db.execute(text("SELECT 1"))
        # Count connected peers in local database
        peer_count_stmt = select(func.count()).select_from(NodePeer).where(
            NodePeer.localNodeId == settings.NODE_ID,
            NodePeer.status == "CONNECTED",
        )
        peer_count_res = await db.execute(peer_count_stmt)
        connected_peers_count = peer_count_res.scalar_one() or 0

        # Count active transactions in mempool
        mempool_size = await MempoolService.get_mempool_count(db)
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        db_status = "disconnected"

    node = await NodeService.get_local_node(db)
    current_status = node.status if node else "ONLINE"

    return NodeHealthResponse(
        nodeId=settings.NODE_ID,
        status=current_status,
        database=db_status,
        endpoint=settings.ENDPOINT,
        protocolVersion=settings.PROTOCOL_VERSION,
        chainId=settings.CHAIN_ID,
        connectedPeersCount=connected_peers_count,
        mempoolSize=mempool_size,
        latestBlockHeight=0,
        timestamp=datetime.now(timezone.utc),
    )


@router.post(
    "/heartbeat",
    summary="Trigger Local Node Heartbeat Update",
    description="Updates the last heartbeat timestamp for this node.",
)
async def trigger_heartbeat(
    db: AsyncSession = Depends(get_db),
):
    """Manually or periodically record a heartbeat."""
    node = await NodeService.update_heartbeat(db)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local node record not found in database",
        )
    return {
        "message": "Heartbeat updated successfully",
        "nodeId": node.nodeId,
        "lastHeartbeat": node.lastHeartbeat,
        "status": node.status,
    }
