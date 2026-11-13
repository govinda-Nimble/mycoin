import logging
from typing import Any, Dict

from chain.models import Account, Blockchain, BlockchainStatus
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
        gas_price = str(max(blockchain.minGasPrice, 2))

        # 4. Automatically resolve sender sequential nonce from database
        account = Account.objects.filter(address=wallet.address, blockchain=blockchain).first()
        nonce = account.nonce if account else 0

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
