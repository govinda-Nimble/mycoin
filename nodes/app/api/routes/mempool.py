"""
Mempool inspection, queue management, and transaction eviction API endpoints.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.schemas.mempool import MempoolEntryResponse, MempoolStatusResponse
from app.services.mempool_service import MempoolService

logger = logging.getLogger("myc_node.api.mempool")

router = APIRouter(prefix="/mempool", tags=["Mempool"])


@router.get(
    "",
    response_model=MempoolStatusResponse,
    summary="Get Mempool Status and Pending Transactions",
    description="Returns the node's local mempool queue ordered by gas price priority and FIFO arrival.",
)
async def get_mempool(
    db: AsyncSession = Depends(get_db),
) -> MempoolStatusResponse:
    """Retrieve full mempool overview."""
    return await MempoolService.get_mempool_status(db)


@router.get(
    "/{tx_hash}",
    response_model=MempoolEntryResponse,
    summary="Get Specific Mempool Entry",
    description="Inspect a pending transaction currently residing in this node's mempool.",
)
async def get_mempool_entry(
    tx_hash: str,
    db: AsyncSession = Depends(get_db),
) -> MempoolEntryResponse:
    """Query a single mempool record by transaction hash."""
    entry = await MempoolService.get_entry_by_hash(db, tx_hash)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{tx_hash}' not found in mempool.",
        )
    return MempoolEntryResponse.model_validate(entry)


@router.delete(
    "/{tx_hash}",
    summary="Evict Transaction from Mempool",
    description="Removes a transaction from the local mempool queue.",
)
async def evict_mempool_transaction(
    tx_hash: str,
    db: AsyncSession = Depends(get_db),
):
    """Evict a transaction from the mempool."""
    removed = await MempoolService.remove_from_mempool(db, tx_hash)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{tx_hash}' not found in mempool to evict.",
        )
    return {
        "message": "Transaction evicted from mempool successfully",
        "txHash": tx_hash,
    }

