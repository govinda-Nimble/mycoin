from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class UseCaseResult:
    """Standardized response across all ledger use cases."""
    success: bool
    reason: str
    status_code: int
    data: Optional[Any] = None
    step: Optional[str] = None


class TransactionValidator(Protocol):
    """Abstract contract for validating and enqueuing signed transactions into the mempool."""

    def validate_and_enqueue(self, payload: dict[str, Any], *, node: Optional[Any] = None) -> Any:
        ...


class LedgerReader(Protocol):
    """Abstract contract for querying transactions and finalized blocks."""

    def find_transaction_by_hash(self, tx_hash: str) -> Optional[Any]:
        ...

    def find_block_by_height(self, chain_id: int, height: int) -> Optional[Any]:
        ...


class MempoolBatchProcessor(Protocol):
    """Abstract contract for packaging mempool transactions into blocks."""

    def process_batch(self, *, chain_id: Optional[int] = None, batch_size: int = 50) -> Any:
        ...

