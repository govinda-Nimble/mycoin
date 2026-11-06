"""
Pydantic v2 schemas for P2P transaction gossip propagation.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.transaction import SignedTransactionPayload


class PropagatedTransactionPayload(SignedTransactionPayload):
    """Transaction payload wrapped with gossip routing metadata."""
    originNodeId: Optional[str] = Field(
        default=None,
        description="Node ID of the peer that forwarded this transaction",
    )
    hopCount: int = Field(
        default=0,
        ge=0,
        description="Number of P2P hops this transaction has traversed",
    )


class PeerPropagationStatus(BaseModel):
    """Propagation status for a single peer."""
    peerNodeId: str
    endpoint: str
    status: str  # "ACCEPTED", "ALREADY_KNOWN", "FAILED"
    error: Optional[str] = None


class PropagationResult(BaseModel):
    """Aggregate result of broadcasting a transaction to peers."""
    txHash: str
    peersContacted: int
    peersAccepted: int
    results: List[PeerPropagationStatus]

