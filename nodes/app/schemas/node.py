"""
Pydantic v2 schemas for Node data exchange and API responses.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class NodeBase(BaseModel):
    """Base node properties."""
    nodeId: str = Field(..., description="Unique node identity, e.g. myc-node-001")
    nodeType: str = Field(default="FULL", description="Node type: FULL or VALIDATOR")
    endpoint: str = Field(..., description="Communication endpoint URL")
    protocolVersion: str = Field(default="v1.0.0", description="Protocol version")


class NodeCreate(NodeBase):
    """Schema for registering or creating a node."""
    status: str = Field(default="ONLINE", description="Node status")
    p2pPublicKey: str = Field(..., description="Hex-encoded ECDSA public key")


class NodeStatusUpdate(BaseModel):
    """Schema for updating node status."""
    status: Optional[str] = None
    endpoint: Optional[str] = None


class NodeInfoResponse(BaseModel):
    """Detailed node information returned by /api/v1/node/info."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    nodeId: str
    nodeType: str
    endpoint: str
    status: str
    protocolVersion: str
    p2pPublicKey: str
    chainId: int
    lastHeartbeat: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class NodeHealthResponse(BaseModel):
    """Diagnostic health information returned by /api/v1/node/health."""
    nodeId: str
    status: str
    database: str
    endpoint: str
    protocolVersion: str
    chainId: int
    connectedPeersCount: int = 0
    mempoolSize: int = 0
    latestBlockHeight: int = 0
    timestamp: datetime

