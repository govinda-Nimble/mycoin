import logging
from typing import Any
from wallets.domain import TransactionSigner, UseCaseResult

logger = logging.getLogger(__name__)


class SignTransactionUseCase:
    """
    Application use case: Orchestrates transaction signing for an authenticated user.
    """

    def __init__(self, transaction_signer: TransactionSigner):
        self._signer = transaction_signer

    def execute(
        self,
        *,
        user: Any,
        receiver_address: str,
        amount: str,
    ) -> UseCaseResult:
        try:
            signed_tx = self._signer.sign_transaction(
                user=user,
                receiver_address=receiver_address,
                amount=amount,
            )
            return UseCaseResult(
                success=True,
                reason="Transaction signed successfully.",
                status_code=200,
                data=signed_tx,
            )
        except ValueError as err:
            return UseCaseResult(
                success=False,
                reason=str(err),
                status_code=400,
            )
        except Exception as err:
            logger.exception("Failed to sign transaction: %s", err)
            return UseCaseResult(
                success=False,
                reason=f"Failed to sign transaction: {err}",
                status_code=500,
            )

