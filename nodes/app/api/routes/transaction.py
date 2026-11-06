"""
Transaction ingestion, validation, query, and P2P gossip propagation API endpoints.
"""

import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, verify_network_key
from app.core.config import settings
from app.schemas.propagation import PropagatedTransactionPayload
from app.schemas.transaction import (
    SignedTransactionPayload,
    TransactionResponse,
    TransactionStatusResponse,
)
from app.services.propagation_service import PropagationService
from app.services.transaction_service import TransactionService

logger = logging.getLogger("myc_node.api.transaction")

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit Signed Transaction",
    description="Validates ECDSA cryptographic signature, adds to local Mempool, and asynchronously broadcasts to connected peers.",
)
async def submit_transaction(
    payload: SignedTransactionPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse:
    """Submit a newly signed transaction to this node."""
    try:
        tx = await TransactionService.validate_and_register_transaction(db, payload)

        # Trigger async peer gossip broadcast in background
        background_tasks.add_task(
            PropagationService.broadcast_transaction,
            payload=payload,
            sender_node_id=None,
            hop_count=0,
        )

        return TransactionResponse.model_validate(tx)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error("Unexpected error submitting transaction: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transaction ingestion failed: {str(exc)}",
        )


@router.post(
    "/receive",
    summary="Receive Propagated Transaction from Peer",
    description="Internal P2P endpoint for gossiped transactions. Validates, queues in Mempool, and forwards to other peers.",
)
async def receive_propagated_transaction(
    payload: PropagatedTransactionPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_network_key),
):
    """Handle incoming gossiped transaction from another node."""
    tx_hash = TransactionService.compute_tx_hash(payload, settings.CHAIN_ID)

    # 1. Loop prevention: check if this node already has this transaction
    existing = await TransactionService.get_transaction_by_hash(db, tx_hash)
    if existing:
        logger.info(
            "Node %s already knows tx %s, halting propagation loop",
            settings.NODE_ID,
            tx_hash[:10],
        )
        return {
            "status": "ALREADY_KNOWN",
            "txHash": tx_hash,
            "message": "Transaction already recorded in local database/mempool",
        }

    # 2. Ingest, verify cryptography, and store in local DB + Mempool
    try:
        tx = await TransactionService.validate_and_register_transaction(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gossip ingestion error: {str(exc)}",
        )

    # 3. Continue gossip to remaining peers (excluding the peer that sent it)
    if payload.hopCount < 10:  # Maximum 10 network hops to prevent infinite loops
        background_tasks.add_task(
            PropagationService.broadcast_transaction,
            payload=payload,
            sender_node_id=payload.originNodeId,
            hop_count=payload.hopCount,
        )

    return {
        "status": "ACCEPTED",
        "txHash": tx.txHash,
        "message": "Transaction accepted and queued for block inclusion",
    }


@router.get(
    "/{tx_hash}",
    response_model=TransactionResponse,
    summary="Get Transaction Details by Hash",
    description="Retrieves a verified transaction and its current processing status.",
)
async def get_transaction(
    tx_hash: str,
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse:
    """Query a transaction by its 0x-prefixed SHA-256 hash."""
    tx = await TransactionService.get_transaction_by_hash(db, tx_hash)
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction with hash '{tx_hash}' not found on this node.",
        )
    return TransactionResponse.model_validate(tx)


@router.get(
    "/{tx_hash}/status",
    response_model=TransactionStatusResponse,
    summary="Get Transaction Status",
    description="Returns lightweight status confirmation for a given transaction hash.",
)
async def get_transaction_status(
    tx_hash: str,
    db: AsyncSession = Depends(get_db),
) -> TransactionStatusResponse:
    """Lightweight status query for client polling."""
    tx = await TransactionService.get_transaction_by_hash(db, tx_hash)
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction with hash '{tx_hash}' not found on this node.",
        )
    return TransactionStatusResponse(
        txHash=tx.txHash,
        status=tx.status,
        senderAddress=tx.senderAddress,
        receiverAddress=tx.receiverAddress,
        amount=tx.amount,
        blockHeight=tx.blockHeight,
        receivedAt=tx.receivedAt,
    )
