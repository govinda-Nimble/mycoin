"""
Mempool service managing transaction prioritization, TTL tracking, and queue inspection.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.mempool import Mempool
from app.models.transaction import Transaction
from app.schemas.mempool import MempoolEntryResponse, MempoolStatusResponse

logger = logging.getLogger("myc_node.service.mempool")


class MempoolService:
    """Service handling local node Mempool operations."""

    @staticmethod
    async def add_to_mempool(db: AsyncSession, tx: Transaction) -> Mempool:
        """
        Calculates transaction fee, prioritizes by gasPrice, and queues
        the transaction in the node's local Mempool.
        """
        # Check if already in mempool
        stmt = select(Mempool).where(Mempool.txHash == tx.txHash)
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            return existing

        # Fee calculation: gasLimit * gasPrice
        gas_price_int = int(tx.gasPrice) if tx.gasPrice.isdigit() else 2
        fee_int = tx.gasLimit * gas_price_int
        priority_val = gas_price_int

        entry = Mempool(
            txHash=tx.txHash,
            senderAddress=tx.senderAddress,
            receiverAddress=tx.receiverAddress,
            amount=tx.amount,
            fee=str(fee_int),
            priority=priority_val,
            status="PENDING",
            addedAt=datetime.now(timezone.utc),
        )
        db.add(entry)

        # Update transaction status to MEMPOOL
        tx.status = "MEMPOOL"

        await db.commit()
        await db.refresh(entry)

        logger.info(
            "Node %s added tx %s to Mempool (fee=%d, priority=%d)",
            settings.NODE_ID,
            tx.txHash[:10],
            fee_int,
            priority_val,
        )
        return entry

    @staticmethod
    async def get_mempool_entries(db: AsyncSession, limit: int = 100) -> List[Mempool]:
        """
        Retrieve mempool entries ordered by priority descending (highest gas price first)
        and addedAt ascending (FIFO for identical gas prices).
        """
        stmt = (
            select(Mempool)
            .where(Mempool.status == "PENDING")
            .order_by(Mempool.priority.desc(), Mempool.addedAt.asc())
            .limit(limit)
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_mempool_count(db: AsyncSession) -> int:
        """Count the number of active pending transactions in the mempool."""
        stmt = select(func.count()).select_from(Mempool).where(Mempool.status == "PENDING")
        res = await db.execute(stmt)
        return res.scalar_one() or 0

    @staticmethod
    async def get_mempool_status(db: AsyncSession) -> MempoolStatusResponse:
        """Produce comprehensive mempool status summary."""
        entries = await MempoolService.get_mempool_entries(db)
        total_fees = sum(int(e.fee) for e in entries if e.fee.isdigit())

        entry_responses = [MempoolEntryResponse.model_validate(e) for e in entries]

        return MempoolStatusResponse(
            nodeId=settings.NODE_ID,
            totalCount=len(entry_responses),
            totalFees=str(total_fees),
            entries=entry_responses,
        )

    @staticmethod
    async def get_entry_by_hash(db: AsyncSession, tx_hash: str) -> Optional[Mempool]:
        """Fetch a specific mempool entry by transaction hash."""
        clean_hash = tx_hash.lower()
        stmt = select(Mempool).where(Mempool.txHash == clean_hash)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def remove_from_mempool(db: AsyncSession, tx_hash: str) -> bool:
        """Evict a transaction from the local mempool."""
        entry = await MempoolService.get_entry_by_hash(db, tx_hash)
        if not entry:
            return False

        await db.delete(entry)
        await db.commit()
        logger.info("Evicted tx %s from Mempool on node %s", tx_hash[:10], settings.NODE_ID)
        return True

