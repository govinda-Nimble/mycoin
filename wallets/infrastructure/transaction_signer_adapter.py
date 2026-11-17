import logging
from typing import Any, Dict

from django.db.models import Max
from django.utils import timezone

from chain.models import Account, Blockchain, BlockchainStatus
from ledger.models import MempoolStatus, MempoolTransaction, Transaction, TransactionStatus
from wallets.domain import TransactionSigner
from wallets.models import Wallet, WalletStatus
from wallets.services.transaction_signer import sign_transaction_payload

logger = logging.getLogger(__name__)


class Secp256k1TransactionSignerAdapter(TransactionSigner):
    """
    Infrastructure implementation of TransactionSigner.
    Communicates directly with the database to resolve wallet, active blockchain,
    and sender nonce, then executes SECP256k1 signing using common cryptographic helpers.
    """

    def sign_transaction(
        self,
        *,
        user: Any,
        receiver_address: str,
        amount: str,
    ) -> Dict[str, Any]:
        # 1. Fetch user's active wallet from database
        wallet = Wallet.objects.filter(user=user, status=WalletStatus.ACTIVE).first()
        if not wallet:
            raise ValueError("User does not have an active wallet.")

        if not wallet.keyReference:
            raise ValueError("User wallet does not have a private key stored for signing.")

        # 2. Fetch active blockchain network configuration from database
        blockchain = Blockchain.objects.filter(status=BlockchainStatus.ACTIVE).first()
        if not blockchain:
            raise ValueError("No active blockchain configured.")

        # 3. Automatically resolve gasLimit, gasPrice, and chainId
        chain_id = blockchain.chainId
        gas_limit = blockchain.baseTransferGas
        gas_price = str(blockchain.minGasPrice)
        # 4. Automatically resolve sender sequential nonce from database
        account = Account.objects.filter(address=wallet.address, blockchain=blockchain).first()
        account_nonce = account.nonce if account else 0

        now = timezone.now()
        if account:
            # Clean up any expired mempool transactions for this account first
            expired_mtxs = MempoolTransaction.objects.filter(
                transaction__blockchain=blockchain,
                transaction__sender=account,
                status=MempoolStatus.ACTIVE,
                expiresAt__lte=now,
            )
            if expired_mtxs.exists():
                expired_tx_ids = list(expired_mtxs.values_list("transaction_id", flat=True))
                expired_mtxs.update(status=MempoolStatus.EXPIRED)
                Transaction.objects.filter(
                    id__in=expired_tx_ids,
                    status=TransactionStatus.PENDING,
                    block__isnull=True,
                ).update(status=TransactionStatus.DROPPED)

            # Ensure account.nonce accounts for all transactions already included in blocks (finalized or failed)
            max_block_nonce = Transaction.objects.filter(
                blockchain=blockchain,
                sender=account,
                block__isnull=False,
            ).aggregate(max_nonce=Max("nonce"))["max_nonce"]

            if max_block_nonce is not None and max_block_nonce >= account.nonce:
                account.nonce = max_block_nonce + 1
                account.save(update_fields=["nonce", "updatedAt"])
                account_nonce = account.nonce

            # Query only live, unexpired pending transactions in the mempool
            pending_txs = Transaction.objects.filter(
                blockchain=blockchain,
                sender=account,
                status=TransactionStatus.PENDING,
                block__isnull=True,
                mempool_entries__status=MempoolStatus.ACTIVE,
                mempool_entries__expiresAt__gt=now,
            ).distinct()

            nonce = account_nonce
            # If there is a pending transaction with the current account nonce, assign a new nonce
            if pending_txs.filter(nonce=account_nonce).exists():
                max_pending_nonce = pending_txs.aggregate(max_nonce=Max("nonce"))["max_nonce"]
                if max_pending_nonce is not None:
                    nonce = max(max_pending_nonce + 1, account_nonce + pending_txs.count())
                else:
                    nonce = account_nonce + 1
        else:
            nonce = 0

        # 5. Sign the payload using common cryptographic service function
        signing_key = wallet.get_signing_key()
        signature_hex, _ = sign_transaction_payload(
            signing_key=signing_key,
            chain_id=chain_id,
            sender_address=wallet.address,
            receiver_address=receiver_address,
            amount=amount,
            nonce=nonce,
            gas_limit=gas_limit,
            gas_price=gas_price,
        )

        user_identifier = getattr(user, "email", str(user))
        logger.info(
            "User %s signed transaction: %s -> %s (amount: %s, nonce: %d)",
            user_identifier,
            wallet.address,
            receiver_address,
            amount,
            nonce,
        )

        # 6. Format output with camelCase keys ready for node broadcast
        return {
            "senderAddress": wallet.address,
            "receiverAddress": receiver_address,
            "amount": str(amount),
            "nonce": nonce,
            "gasLimit": gas_limit,
            "gasPrice": str(gas_price),
            "publicKey": wallet.publicKey,
            "signature": signature_hex,
        }
