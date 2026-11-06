"""
Transaction signing service.

Constructs canonical transaction serialization payloads, computes deterministic
ECDSA secp256k1 signatures, and formats camelCase payload responses ready for node broadcast.
All blockchain parameters (gasLimit, gasPrice, nonce, chainId) are resolved automatically by the backend.
"""

import hashlib
import logging
from typing import Any, Dict, Tuple

import ecdsa

from network.models import Blockchain, BlockchainStatus
from wallets.models import Account, Wallet, WalletStatus

logger = logging.getLogger(__name__)


def serialize_transaction_for_signing(
    chain_id: int,
    sender_address: str,
    receiver_address: str,
    amount: str,
    nonce: int,
    gas_limit: int,
    gas_price: str,
) -> bytes:
    """
    Constructs a deterministic canonical string representation of a transaction
    and returns its SHA-256 digest bytes for cryptographic signing.
    """
    canonical_payload = (
        f"{chain_id}:"
        f"{sender_address.lower()}:"
        f"{receiver_address.lower()}:"
        f"{amount}:"
        f"{nonce}:"
        f"{gas_limit}:"
        f"{gas_price}"
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).digest()


def sign_transaction_payload(
    signing_key: ecdsa.SigningKey,
    chain_id: int,
    sender_address: str,
    receiver_address: str,
    amount: str,
    nonce: int,
    gas_limit: int,
    gas_price: str,
) -> Tuple[str, str]:
    """
    Generates a deterministic ECDSA secp256k1 signature for a transaction payload.

    Returns:
        Tuple[str, str]: (signature_hex_with_0x, payload_hash_hex)
    """
    payload_digest = serialize_transaction_for_signing(
        chain_id=chain_id,
        sender_address=sender_address,
        receiver_address=receiver_address,
        amount=amount,
        nonce=nonce,
        gas_limit=gas_limit,
        gas_price=gas_price,
    )

    # 64-byte raw signature (r + s) as lowercase hex
    raw_signature_bytes = signing_key.sign_deterministic(
        payload_digest,
        hashfunc=hashlib.sha256,
        sigencode=ecdsa.util.sigencode_string,
    )
    signature_hex = "0x" + raw_signature_bytes.hex().lower()
    payload_hash_hex = payload_digest.hex().lower()

    return signature_hex, payload_hash_hex


def sign_transaction_for_user(
    *,
    user: Any,
    receiver_address: str,
    amount: str,
) -> Dict[str, Any]:
    """
    Signs a transfer transaction on behalf of an authenticated user using their stored wallet.
    User supplies only `amount` and `receiver_address`; all other parameters (gasLimit, gasPrice,
    nonce, chainId) are resolved automatically by the backend.

    Returns:
        Dict[str, Any]: Formatted signed transaction payload with camelCase variables.
    """
    # 1. Fetch user's active wallet
    wallet = Wallet.objects.filter(user=user, status=WalletStatus.ACTIVE).first()
    if not wallet:
        raise ValueError("User does not have an active wallet.")

    if not wallet.keyReference:
        raise ValueError("User wallet does not have a private key stored for signing.")

    # 2. Fetch active blockchain network configuration
    blockchain = Blockchain.objects.filter(status=BlockchainStatus.ACTIVE).first()
    if not blockchain:
        raise ValueError("No active blockchain configured.")

    # 3. Backend automatically resolves gasLimit, gasPrice, and chainId
    chain_id = blockchain.chainId
    gas_limit = blockchain.baseTransferGas
    gas_price = str(max(blockchain.minGasPrice, 2))

    # 4. Backend automatically resolves sender sequential nonce
    account = Account.objects.filter(wallet=wallet, blockchain=blockchain).first()
    nonce = account.nonce if account else 0

    # 5. Sign the payload using wallet's private key
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

    logger.info(
        "User %s signed transaction: %s -> %s (amount: %s, nonce: %d)",
        user.email,
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
