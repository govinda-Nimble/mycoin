from typing import Any
from wallets.domain import TransactionSigner
from wallets.services.transaction_signer import sign_transaction_for_user


class Secp256k1TransactionSignerAdapter(TransactionSigner):
    """
    Infrastructure implementation of TransactionSigner using SECP256k1 ECDSA cryptography.
    """

    def sign_transaction(
        self,
        *,
        user: Any,
        receiver_address: str,
        amount: str,
    ) -> dict[str, Any]:
        return sign_transaction_for_user(
            user=user,
            receiver_address=receiver_address,
            amount=amount,
        )

