from typing import Any, Optional
from wallets.domain import WalletReader, WalletWriter
from wallets.models import Wallet, WalletStatus
from wallets.services.wallet_service import create_wallet_for_user


class DjangoWalletRepository(WalletReader, WalletWriter):
    """
    Infrastructure implementation of WalletReader and WalletWriter using Django ORM.
    """

    def find_by_user(self, user: Any) -> Optional[Wallet]:
        return Wallet.objects.filter(user=user, status=WalletStatus.ACTIVE).first()

    def find_by_address(self, address: str) -> Optional[Wallet]:
        return Wallet.objects.filter(address=address.lower()).first()

    def create_wallet_for_user(self, user: Any, name: str = "") -> Wallet:
        return create_wallet_for_user(user, name=name)

