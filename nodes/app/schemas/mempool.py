"""
Pydantic v2 schemas for node Mempool status and transaction inspection.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class MempoolEntryResponse(BaseModel):
    """Mempool entry representation."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    txHash: str
    senderAddress: str
    receiverAddress: str
    amount: str
    fee: str
    priority: int
    status: str
    addedAt: datetime
    expiresAt: Optional[datetime] = None


class MempoolStatusResponse(BaseModel):
    """Mempool diagnostic overview response."""
    nodeId: str
    totalCount: int
    totalFees: str
    entries: List[MempoolEntryResponse]

