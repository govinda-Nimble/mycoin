from typing import Any, Optional
from wallets.domain import AccountReader
from wallets.services.wallet_service import get_account_balance


class DjangoAccountRepository(AccountReader):
    """
    Infrastructure implementation of AccountReader using Django ORM and balance resolution service.
    """

    def get_balance(
        self,
        *,
        user: Optional[Any] = None,
        address: Optional[str] = None,
        chain_id: Optional[int] = None,
    ) -> dict[str, Any]:
        return get_account_balance(
            user=user,
            address=address,
            chain_id=chain_id,
        )

