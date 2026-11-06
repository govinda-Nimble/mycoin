"""
Peer discovery, handshake, and P2P connection API endpoints.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, verify_network_key
from app.schemas.peer import (
    PeerConnectRequest,
    PeerHandshakeRequest,
    PeerListResponse,
    PeerResponse,
    PingResponse,
)
from app.services.peer_service import PeerService

logger = logging.getLogger("myc_node.api.peer")

router = APIRouter(prefix="/peers", tags=["Peer Networking"])


@router.post(
    "/connect",
    response_model=PeerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect to a Remote Peer",
    description="Initiates outbound P2P connection to another node endpoint, performs network validation, and runs bidirectional handshake.",
)
async def connect_peer(
    payload: PeerConnectRequest,
    db: AsyncSession = Depends(get_db),
) -> PeerResponse:
    """Connect to a peer by endpoint URL."""
    try:
        return await PeerService.connect_to_peer(db, payload.peerEndpoint)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.error("Unexpected error connecting to peer: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to peer: {str(exc)}",
        )


@router.post(
    "/handshake",
    response_model=PeerResponse,
    summary="Receive Inbound Peer Handshake",
    description="Endpoint invoked by remote peers when establishing a bidirectional P2P connection.",
)
async def receive_handshake(
    handshake: PeerHandshakeRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_network_key),
) -> PeerResponse:
    """Handle incoming peer handshake."""
    try:
        return await PeerService.handle_handshake(db, handshake)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error("Error during peer handshake: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Handshake error: {str(exc)}",
        )


@router.get(
    "",
    response_model=PeerListResponse,
    summary="List Known and Connected Peers",
    description="Returns the list of all peers recorded in this node's isolated database.",
)
async def list_peers(
    db: AsyncSession = Depends(get_db),
) -> PeerListResponse:
    """List all peers tracked by this node."""
    return await PeerService.list_peers(db)


@router.delete(
    "/{peer_node_id}",
    summary="Disconnect a Peer",
    description="Marks a peer relationship as DISCONNECTED in the local database.",
)
async def disconnect_peer(
    peer_node_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Disconnect from a peer node."""
    success = await PeerService.disconnect_peer(db, peer_node_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Peer '{peer_node_id}' not found in local peer list",
        )
    return {
        "message": f"Peer '{peer_node_id}' disconnected successfully",
        "peerNodeId": peer_node_id,
        "status": "DISCONNECTED",
    }


@router.post(
    "/{peer_node_id}/ping",
    response_model=PingResponse,
    summary="Ping a Peer",
    description="Pings a connected peer's health endpoint to check responsiveness and measure round-trip latency.",
)
async def ping_peer(
    peer_node_id: str,
    db: AsyncSession = Depends(get_db),
) -> PingResponse:
    """Measure latency and connectivity to a known peer."""
    try:
        return await PeerService.ping_peer(db, peer_node_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Ping to peer '{peer_node_id}' failed: {str(exc)}",
        )

