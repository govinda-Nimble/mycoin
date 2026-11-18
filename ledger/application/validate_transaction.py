import logging
from typing import Any
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError

from common.models import ImmutableRecordError
from common.utils import format_database_constraint_error
from ledger.domain import TransactionValidator, UseCaseResult
from ledger.services.transaction_validator import TransactionValidationError

logger = logging.getLogger(__name__)


class ValidateTransactionUseCase:
    """
    Application use case: Validates an incoming signed transaction and enqueues it into the mempool.
    """

    def __init__(self, transaction_validator: TransactionValidator):
        self._validator = transaction_validator

    def execute(self, *, payload: dict[str, Any]) -> UseCaseResult:
        try:
            result = self._validator.validate_and_enqueue(payload)
            tx = result.transaction
            mempool = result.mempool_entry

            response_data = {
                "txHash": result.tx_hash,
                "senderAddress": tx.sender.address,
                "receiverAddress": tx.receiverAddress,
                "amount": str(tx.amount),
                "nonce": tx.nonce,
                "gasLimit": tx.gasLimit,
                "gasPrice": str(tx.gasPrice),
                "fee": tx.gasLimit * tx.gasPrice,
                "status": tx.status,
                "mempoolStatus": mempool.status,
                "mempoolEntryId": str(mempool.id),
                "nodeId": mempool.node.nodeId,
                "arrivalTime": mempool.arrivalTime.isoformat(),
                "expiresAt": mempool.expiresAt.isoformat(),
            }

            # # Gossip original signed transaction data to connected peers
            # try:
            #     from ledger.services.gossip import gossip_transaction_to_peers
            #     gossip_transaction_to_peers(payload, mempool.node)
            # except Exception as exc:
            #     logger.warning("Peer gossip encountered an issue: %s", exc)

            return UseCaseResult(
                success=True,
                reason=result.message,
                status_code=201,
                data=response_data,
            )
        except TransactionValidationError as err:
            return UseCaseResult(
                success=False,
                reason=err.message,
                status_code=400,
                step=err.step,
            )
        except (IntegrityError, DjangoValidationError, ImmutableRecordError) as err:
            clean_err = format_database_constraint_error(err)
            return UseCaseResult(
                success=False,
                reason=clean_err,
                status_code=400,
                step="CHECK_CONSTRAINTS",
            )
        except Exception as err:
            logger.exception("Unexpected error in ValidateTransactionUseCase: %s", err)
            return UseCaseResult(
                success=False,
                reason="An unexpected internal error occurred during transaction processing.",
                status_code=500,
            )

