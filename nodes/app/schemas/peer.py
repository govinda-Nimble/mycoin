"""
Pydantic v2 schemas for peer management, handshakes, and peer lists.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class PeerConnectRequest(BaseModel):
    """Payload to initiate an outbound peer connection."""
    peerEndpoint: str = Field(
        ...,
        description="Target node HTTP endpoint, e.g. http://localhost:8002",
        examples=["http://localhost:8002"],
    )


class PeerHandshakeRequest(BaseModel):
    """Payload exchanged during bidirectional peer handshake."""
    nodeId: str = Field(..., description="Identity of the connecting node")
    nodeType: str = Field(default="FULL", description="FULL or VALIDATOR")
    endpoint: str = Field(..., description="Endpoint URL of the connecting node")
    protocolVersion: str = Field(default="v1.0.0", description="Protocol version")
    chainId: int = Field(..., description="Blockchain network chain ID")
    p2pPublicKey: str = Field(..., description="ECDSA public key")


class PeerResponse(BaseModel):
    """Peer information representation."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    localNodeId: str
    peerNodeId: str
    endpoint: Optional[str] = None
    status: str
    lastConnectedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class PeerListResponse(BaseModel):
    """Summary of all peers known to this node."""
    totalCount: int
    connectedCount: int
    peers: List[PeerResponse]


class PingResponse(BaseModel):
    """Result of pinging a remote peer."""
    peerNodeId: str
    endpoint: str
    status: str
    latencyMs: float
    timestamp: datetime

