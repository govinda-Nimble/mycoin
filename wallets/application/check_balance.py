import logging
from typing import Any, Optional
from wallets.domain import AccountReader, UseCaseResult

logger = logging.getLogger(__name__)


class CheckBalanceUseCase:
    """
    Application use case: Queries and calculates account balance and mempool pending state.
    """

    def __init__(self, account_reader: AccountReader):
        self._account_reader = account_reader

    def execute(
        self,
        *,
        user: Optional[Any] = None,
        address: Optional[str] = None,
        chain_id: Optional[int] = None,
    ) -> UseCaseResult:
        try:
            balance_data = self._account_reader.get_balance(
                user=user,
                address=address,
                chain_id=chain_id,
            )
            return UseCaseResult(
                success=True,
                reason="Balance retrieved successfully.",
                status_code=200,
                data=balance_data,
            )
        except ValueError as err:
            return UseCaseResult(
                success=False,
                reason=str(err),
                status_code=400,
            )
        except Exception as err:
            logger.exception("Failed to retrieve balance: %s", err)
            return UseCaseResult(
                success=False,
                reason=f"Failed to retrieve balance: {err}",
                status_code=500,
            )

