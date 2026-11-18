from typing import Any, Optional
from ledger.domain import TransactionValidator
from ledger.services.transaction_validator import validate_and_enqueue_transaction


class DjangoTransactionValidatorAdapter(TransactionValidator):
    """
    Infrastructure implementation of TransactionValidator delegating to the domain validation pipeline.
    """

    def validate_and_enqueue(self, payload: dict[str, Any], *, node: Optional[Any] = None) -> Any:
        return validate_and_enqueue_transaction(payload, node=node)

