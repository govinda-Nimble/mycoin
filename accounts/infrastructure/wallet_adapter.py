"""
Wallet adapter implementing WalletCreator domain protocol.
Connects the accounts domain to the wallets application service.
"""

from typing import Any
from wallets.services.wallet_service import create_wallet_for_user


class DjangoWalletAdapter:
    """
    Implements WalletCreator protocol by creating a secure keystore Wallet for the User.
    """

    def create_wallet_for_user(self, user: Any) -> Any:
        return create_wallet_for_user(user)

