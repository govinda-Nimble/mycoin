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
    Convenience wrapper for non-API callers, tests, and seeders.
    Delegates to the infrastructure layer Secp256k1TransactionSignerAdapter.
    """
    from wallets.infrastructure.transaction_signer_adapter import Secp256k1TransactionSignerAdapter

    adapter = Secp256k1TransactionSignerAdapter()
    return adapter.sign_transaction(
        user=user,
        receiver_address=receiver_address,
        amount=amount,
    )
