"""
Mempool transaction processing and batch selection service.

Monitors the local Mempool, filters eligible active transactions,
enforces database-level concurrency protection, and prepares transaction batches
for upcoming consensus, block production, and validation stages.
"""

from dataclasses import dataclass, field
import logging
import time
from typing import List, Optional

from django.db import connection, transaction
from django.utils import timezone

from ledger.models import (
    MempoolStatus,
    MempoolTransaction,
    Transaction,
    TransactionStatus,
)
from ledger.services.block_producer import (
    produce_block_from_mempool,
    select_transactions_for_block,
)
from network.models import Blockchain, BlockchainStatus

logger = logging.getLogger("ledger.mempool_processor")

# Default processor configuration
DEFAULT_BATCH_SIZE: int = 5
DEFAULT_INTERVAL_SECONDS: int = 60

# PostgreSQL advisory lock ID for mempool processor coordination (arbitrary unique 64-bit int)
MEMPOOL_PROCESSOR_LOCK_KEY: int = 1001001


@dataclass
class MempoolProcessingResult:
    """Structured result returned by each mempool processing execution."""
    blockchain_id: Optional[str] = None
    chain_id: Optional[int] = None
    total_eligible_count: int = 0
    batch_size: int = DEFAULT_BATCH_SIZE
    selected_count: int = 0
    transactions: List[MempoolTransaction] = field(default_factory=list)
    produced_block_height: Optional[int] = None
    produced_block_hash: Optional[str] = None
    duration_seconds: float = 0.0
    status: str = "EMPTY"  # "EMPTY", "BATCH_PROCESSED", "BATCH_SELECTED", "LOCK_UNAVAILABLE", "NO_BLOCKCHAIN", "ERROR"
    message: str = ""


def try_acquire_advisory_lock() -> bool:
    """
    Attempts to acquire a PostgreSQL transaction-level advisory lock.
    Returns True if lock acquired, or False if another process holds it.
    Gracefully passes (returns True) on non-PostgreSQL engines (e.g. SQLite in unit tests).
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s);", [MEMPOOL_PROCESSOR_LOCK_KEY])
            row = cursor.fetchone()
            return bool(row and row[0])
    return True


def process_mempool(
    blockchain: Optional[Blockchain] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    chain_id: Optional[int] = None,
) -> MempoolProcessingResult:
    """
    Scans the mempool for eligible active transactions, selects a prioritized batch,
    and returns a structured processing result protected by database-level locks.

    Filters strictly for:
    - MempoolTransaction.status == MempoolStatus.ACTIVE
    - MempoolTransaction.expiresAt > timezone.now() (unexpired)
    - Transaction.status == TransactionStatus.PENDING
    - Transaction.block is null (not yet included in any block)
    - Transaction belongs to the active MYCOIN blockchain

    Args:
        blockchain: Optional pre-resolved Blockchain instance.
        batch_size: Maximum number of transactions to retrieve in one batch.
        chain_id: Optional chain ID to target a specific blockchain.

    Returns:
        MempoolProcessingResult containing the execution outcome and selected transactions.
    """
    start_time = time.perf_counter()
    now = timezone.now()

    # 1. Resolve target Blockchain
    if blockchain is None:
        if chain_id is not None:
            blockchain = Blockchain.objects.filter(chainId=chain_id).first()
        else:
            blockchain = Blockchain.objects.filter(status=BlockchainStatus.ACTIVE).first()

    if not blockchain:
        duration = round(time.perf_counter() - start_time, 4)
        logger.warning("No active blockchain network found. Mempool processing skipped.")
        return MempoolProcessingResult(
            duration_seconds=duration,
            status="NO_BLOCKCHAIN",
            message="No active blockchain network found.",
        )

    # 2. Execute within an atomic transaction with row & advisory locks
    with transaction.atomic():
        # Concurrency protection layer 1: PostgreSQL advisory lock
        if not try_acquire_advisory_lock():
            duration = round(time.perf_counter() - start_time, 4)
            logger.warning("Mempool processor lock is held by another worker. Skipping cycle.")
            return MempoolProcessingResult(
                blockchain_id=str(blockchain.id),
                chain_id=blockchain.chainId,
                duration_seconds=duration,
                status="LOCK_UNAVAILABLE",
                message="Processor lock is currently held by another worker.",
            )

        # 3. Clean up expired active mempool transactions and mark un-blocked transactions as DROPPED
        expired_mempool_entries = MempoolTransaction.objects.filter(
            status=MempoolStatus.ACTIVE,
            expiresAt__lte=now,
        )
        if expired_mempool_entries.exists():
            expired_tx_ids = list(expired_mempool_entries.values_list("transaction_id", flat=True))
            expired_mempool_entries.update(status=MempoolStatus.EXPIRED)
            Transaction.objects.filter(
                id__in=expired_tx_ids,
                status=TransactionStatus.PENDING,
                block__isnull=True,
            ).update(status=TransactionStatus.DROPPED)
            logger.info("Evicted %d expired transaction(s) from mempool.", len(expired_tx_ids))

        # 4. Query total count of eligible active mempool transactions
        eligible_base_qs = MempoolTransaction.objects.filter(
            status=MempoolStatus.ACTIVE,
            expiresAt__gt=now,
            transaction__status=TransactionStatus.PENDING,
            transaction__block__isnull=True,
            transaction__blockchain=blockchain,
        )

        total_eligible_count = eligible_base_qs.count()

        # 5. Handle empty mempool
        if total_eligible_count == 0:
            duration = round(time.perf_counter() - start_time, 4)
            logger.debug(
                "Mempool is empty for chain %d (%s). No transactions to process. Duration: %.4fs",
                blockchain.chainId,
                blockchain.name,
                duration,
            )
            return MempoolProcessingResult(
                blockchain_id=str(blockchain.id),
                chain_id=blockchain.chainId,
                total_eligible_count=0,
                batch_size=batch_size,
                selected_count=0,
                transactions=[],
                duration_seconds=duration,
                status="EMPTY",
                message="Mempool is empty. No eligible transactions available.",
            )

        # 5. Select prioritized transactions using Stage 4 selection service
        selected_batch = select_transactions_for_block(
            blockchain=blockchain,
            batch_size=batch_size,
        )

        duration = round(time.perf_counter() - start_time, 4)

        if not selected_batch:
            logger.warning(
                "Eligible transactions exist (%d) but all candidate rows are locked by concurrent workers.",
                total_eligible_count,
            )
            return MempoolProcessingResult(
                blockchain_id=str(blockchain.id),
                chain_id=blockchain.chainId,
                total_eligible_count=total_eligible_count,
                batch_size=batch_size,
                selected_count=0,
                transactions=[],
                duration_seconds=duration,
                status="LOCK_UNAVAILABLE",
                message="Eligible transactions were locked by another concurrent process.",
            )

        # 6. Produce block and execute transactions atomically
        produced_block = produce_block_from_mempool(
            blockchain=blockchain,
            mempool_entries=selected_batch,
        )

        duration = round(time.perf_counter() - start_time, 4)
        block_height = produced_block.height if produced_block else None
        block_hash = produced_block.blockHash if produced_block else None

        if produced_block:
            logger.info(
                "Mempool batch processed for chain %d: Produced Block #%d (%s) containing %d transaction(s) (duration: %.4fs).",
                blockchain.chainId,
                block_height,
                block_hash[:12],
                len(selected_batch),
                duration,
            )
            msg = f"Successfully produced Block #{block_height} ({block_hash[:12]}) containing {len(selected_batch)} transaction(s)."
        else:
            logger.info(
                "Mempool batch selected for chain %d: %d/%d eligible transaction(s) (batch size: %d, duration: %.4fs).",
                blockchain.chainId,
                len(selected_batch),
                total_eligible_count,
                batch_size,
                duration,
            )
            msg = f"Successfully selected {len(selected_batch)} transaction(s) from mempool."

        return MempoolProcessingResult(
            blockchain_id=str(blockchain.id),
            chain_id=blockchain.chainId,
            total_eligible_count=total_eligible_count,
            batch_size=batch_size,
            selected_count=len(selected_batch),
            transactions=selected_batch,
            produced_block_height=block_height,
            produced_block_hash=block_hash,
            duration_seconds=duration,
            status="BATCH_PROCESSED" if produced_block else "BATCH_SELECTED",
            message=msg,
        )

