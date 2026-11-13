from typing import Any, Dict, Optional
from django.utils import timezone

from chain.models import Account, Blockchain, BlockchainStatus
from ledger.models import MempoolStatus, MempoolTransaction, TransactionStatus
from wallets.domain import AccountReader
from wallets.models import Wallet, WalletStatus
from wallets.services.wallet_service import format_coin_amount


class DjangoAccountRepository(AccountReader):
    """
    Infrastructure implementation of AccountReader communicating directly with the database
    to resolve on-chain account balances, mempool pending state, and network status.
    """

    def get_balance(
        self,
        *,
        user: Optional[Any] = None,
        address: Optional[str] = None,
        chain_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        # 1. Resolve Blockchain
        if chain_id is not None:
            blockchain = Blockchain.objects.filter(chainId=chain_id).first()
            if not blockchain:
                raise ValueError(f"Blockchain with chain ID {chain_id} does not exist.")
        else:
            blockchain = Blockchain.objects.filter(status=BlockchainStatus.ACTIVE).first()
            if not blockchain:
                raise ValueError("No active blockchain network configured.")

        # 2. Resolve target Address
        target_address = address
        if not target_address:
            if not user or not user.is_authenticated:
                raise ValueError("Authenticated user or address parameter is required.")
            wallet = Wallet.objects.filter(user=user, status=WalletStatus.ACTIVE).first()
            if not wallet:
                raise ValueError("User does not have an active wallet.")
            target_address = wallet.address

        target_address = target_address.strip().lower()

        # 3. Query Account record on the targeted blockchain
        account = Account.objects.filter(blockchain=blockchain, address=target_address).first()

        balance = account.balance if account else 0
        nonce = account.nonce if account else 0
        account_status = account.status if account else "ACTIVE"

        # 4. Check for active pending transactions in the mempool
        now = timezone.now()
        active_mempool_qs = MempoolTransaction.objects.filter(
            status=MempoolStatus.ACTIVE,
            expiresAt__gt=now,
            transaction__status=TransactionStatus.PENDING,
            transaction__block__isnull=True,
            transaction__blockchain=blockchain,
            transaction__sender__address=target_address,
        ).select_related("transaction")

        pending_count = active_mempool_qs.count()
        pending_deductions = 0
        if pending_count > 0:
            for mtx in active_mempool_qs:
                tx = mtx.transaction
                fee = tx.gasLimit * tx.gasPrice
                pending_deductions += (tx.amount + fee)

        available_balance = max(0, balance - pending_deductions)

        return {
            "address": target_address,
            "balance": balance,
            "balanceFormatted": format_coin_amount(balance, blockchain.decimals),
            "availableBalance": available_balance,
            "availableBalanceFormatted": format_coin_amount(available_balance, blockchain.decimals),
            "pendingTransactionsCount": pending_count,
            "symbol": blockchain.symbol,
            "decimals": blockchain.decimals,
            "nonce": nonce,
            "chainId": blockchain.chainId,
            "networkName": blockchain.name,
            "status": account_status,
        }
