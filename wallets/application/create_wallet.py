from typing import Any
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError

from common.utils import format_database_constraint_error
from wallets.domain import UseCaseResult, WalletWriter


class CreateWalletUseCase:
    """
    Application use case: Orchestrates new keystore wallet generation for a user.
    """

    def __init__(self, wallet_writer: WalletWriter):
        self._wallet_writer = wallet_writer

    def execute(self, *, user: Any, name: str = "") -> UseCaseResult:
        try:
            wallet = self._wallet_writer.create_wallet_for_user(user, name=name)
            return UseCaseResult(
                success=True,
                reason="Wallet created successfully.",
                status_code=201,
                data={
                    "id": str(wallet.id),
                    "address": wallet.address,
                    "publicKey": wallet.publicKey,
                    "name": wallet.name,
                },
            )
        except (IntegrityError, DjangoValidationError) as err:
            clean_err = format_database_constraint_error(err)
            return UseCaseResult(
                success=False,
                reason=clean_err,
                status_code=400,
            )
        except Exception as err:
            return UseCaseResult(
                success=False,
                reason="Failed to create wallet due to an internal error.",
                status_code=500,
            )

