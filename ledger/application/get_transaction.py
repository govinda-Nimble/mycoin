import logging
from typing import Optional
from ledger.domain import LedgerReader, UseCaseResult

logger = logging.getLogger(__name__)


class GetTransactionUseCase:
    """
    Application use case: Fetches a transaction and its receipt/events by hash.
    """

    def __init__(self, ledger_reader: LedgerReader):
        self._ledger_reader = ledger_reader

    def execute(self, *, tx_hash: str) -> UseCaseResult:
        tx = self._ledger_reader.find_transaction_by_hash(tx_hash)
        if not tx:
            return UseCaseResult(
                success=False,
                reason=f"Transaction with hash '{tx_hash}' not found.",
                status_code=404,
            )

        data = {
            "txHash": tx.hash,
            "senderAddress": tx.sender.address,
            "receiverAddress": tx.receiverAddress,
            "amount": str(tx.amount),
            "nonce": tx.nonce,
            "gasLimit": tx.gasLimit,
            "gasPrice": str(tx.gasPrice),
            "feePaid": tx.feePaid,
            "status": tx.status,
            "blockHeight": tx.block.height if tx.block else None,
            "createdAt": tx.createdAt.isoformat() if tx.createdAt else None,
        }

        return UseCaseResult(
            success=True,
            reason="Transaction retrieved successfully.",
            status_code=200,
            data=data,
        )

