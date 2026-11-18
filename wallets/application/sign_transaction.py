import logging
from typing import Any
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError

from common.models import ImmutableRecordError
from common.utils import format_database_constraint_error
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
        except (IntegrityError, DjangoValidationError, ImmutableRecordError) as err:
            clean_err = format_database_constraint_error(err)
            return UseCaseResult(
                success=False,
                reason=clean_err,
                status_code=400,
            )
        except Exception as err:
            logger.exception("Failed to sign transaction: %s", err)
            return UseCaseResult(
                success=False,
                reason="Failed to sign transaction due to an internal error.",
                status_code=500,
            )

