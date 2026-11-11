"""
Wallet adapter implementing WalletCreator domain protocol.
Connects the accounts domain to the wallets application service.
"""

from typing import Any
from wallets.services.registration_bonus import create_account_and_grant_registration_bonus
from wallets.services.wallet_service import create_wallet_for_user


class DjangoWalletAdapter:
    """
    Implements WalletCreator protocol by creating a secure keystore Wallet for the User,
    and provisioning their on-chain Account with 100 MYC registration bonus from Treasury.
    """

    def create_wallet_for_user(self, user: Any) -> Any:
        return create_wallet_for_user(user)

    def create_account_for_wallet(self, user: Any, wallet: Any) -> Any:
        bonus_result = create_account_and_grant_registration_bonus(user=user, wallet=wallet)
        if bonus_result:
            return bonus_result.account
        return None
