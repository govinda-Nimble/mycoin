"""
Cryptographic validation and transaction ingestion service.
Verifies ECDSA secp256k1 signatures, validates sender addresses against public keys,
and computes deterministic SHA-256 transaction hashes.
"""

import hashlib
import logging
from typing import Optional, Tuple
import ecdsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.transaction import Transaction
from app.schemas.transaction import SignedTransactionPayload
from app.services.mempool_service import MempoolService

logger = logging.getLogger("myc_node.service.transaction")


class TransactionService:
    """Service handling transaction hashing, ECDSA verification, and storage."""

    @staticmethod
    def serialize_canonical_payload(payload: SignedTransactionPayload, chain_id: int) -> str:
        """
        Build the canonical colon-delimited string payload matching the
        wallet signing service specification.
        """
        return (
            f"{chain_id}:"
            f"{payload.senderAddress.lower()}:"
            f"{payload.receiverAddress.lower()}:"
            f"{payload.amount}:"
            f"{payload.nonce}:"
            f"{payload.gasLimit}:"
            f"{payload.gasPrice}"
        )

    @staticmethod
    def compute_payload_digest(payload: SignedTransactionPayload, chain_id: int) -> bytes:
        """Compute the SHA-256 digest bytes of the canonical transaction payload."""
        canonical_str = TransactionService.serialize_canonical_payload(payload, chain_id)
        return hashlib.sha256(canonical_str.encode("utf-8")).digest()

    @staticmethod
    def compute_tx_hash(payload: SignedTransactionPayload, chain_id: int) -> str:
        """
        Compute deterministic unique transaction hash:
        SHA-256(canonical_payload_bytes + raw_signature_bytes).
        """
        canonical_str = TransactionService.serialize_canonical_payload(payload, chain_id)
        clean_sig = payload.signature.lower()
        if clean_sig.startswith("0x"):
            clean_sig = clean_sig[2:]
        sig_bytes = bytes.fromhex(clean_sig)
        tx_hash_digest = hashlib.sha256(canonical_str.encode("utf-8") + sig_bytes).hexdigest().lower()
        return "0x" + tx_hash_digest

    @staticmethod
    def verify_address_derivation(public_key_hex: str, expected_address: str) -> bool:
        """
        Verify that expected_address matches SHA-256(raw_uncompressed_public_key)[-40:].
        """
        clean_pk = public_key_hex.lower()
        if clean_pk.startswith("04"):
            clean_pk = clean_pk[2:]

        if len(clean_pk) != 128:
            return False

        try:
            raw_vk_bytes = bytes.fromhex(clean_pk)
            derived_hash = hashlib.sha256(raw_vk_bytes).hexdigest().lower()
            derived_address = "0x" + derived_hash[-40:]
            return derived_address == expected_address.lower()
        except Exception:
            return False

    @staticmethod
    def verify_cryptographic_signature(
        payload: SignedTransactionPayload,
        chain_id: int,
    ) -> Tuple[bool, str]:
        """
        Cryptographically verifies the transaction:
        1. Validates sender address matches public key derivation.
        2. Validates ECDSA secp256k1 signature against canonical payload digest.
        """
        # 1. Address derivation validation
        if not TransactionService.verify_address_derivation(payload.publicKey, payload.senderAddress):
            return False, f"Sender address '{payload.senderAddress}' does not match public key."

        # 2. Signature format check
        clean_sig = payload.signature.lower()
        if clean_sig.startswith("0x"):
            clean_sig = clean_sig[2:]

        if len(clean_sig) != 128:
            return False, f"Invalid signature length: expected 128 hex characters (64 bytes), got {len(clean_sig)}"

        # 3. Public key format check
        clean_pk = payload.publicKey.lower()
        if clean_pk.startswith("04"):
            clean_pk = clean_pk[2:]

        if len(clean_pk) != 128:
            return False, f"Invalid public key length: expected 128/130 characters, got {len(clean_pk)}"

        # 4. Cryptographic ECDSA secp256k1 verification
        try:
            raw_vk_bytes = bytes.fromhex(clean_pk)
            vk = ecdsa.VerifyingKey.from_string(raw_vk_bytes, curve=ecdsa.SECP256k1)
            digest = TransactionService.compute_payload_digest(payload, chain_id)
            sig_bytes = bytes.fromhex(clean_sig)

            is_valid = vk.verify(
                sig_bytes,
                digest,
                hashfunc=hashlib.sha256,
                sigdecode=ecdsa.util.sigdecode_string,
            )
            if is_valid:
                return True, ""
            return False, "Cryptographic signature verification returned False"
        except ecdsa.BadSignatureError:
            return False, "Invalid cryptographic signature: signature does not match transaction payload"
        except Exception as exc:
            return False, f"Signature validation failed: {str(exc)}"

    @staticmethod
    async def validate_and_register_transaction(
        db: AsyncSession,
        payload: SignedTransactionPayload,
    ) -> Transaction:
        """
        Ingest and cryptographically verify a transaction.
        Checks for duplicates and saves it as PENDING in this node's database.
        """
        # 1. Verify cryptography
        is_valid, reason = TransactionService.verify_cryptographic_signature(
            payload,
            settings.CHAIN_ID,
        )
        if not is_valid:
            logger.warning("Transaction rejected from %s: %s", payload.senderAddress, reason)
            raise ValueError(f"Transaction validation failed: {reason}")

        # 2. Compute transaction hash
        tx_hash = TransactionService.compute_tx_hash(payload, settings.CHAIN_ID)

        # 3. Check for duplicates in local database
        stmt = select(Transaction).where(Transaction.txHash == tx_hash)
        res = await db.execute(stmt)
        existing_tx = res.scalar_one_or_none()

        if existing_tx:
            raise ValueError(f"Duplicate transaction: {tx_hash} already recorded on this node.")

        # 4. Store transaction
        tx = Transaction(
            txHash=tx_hash,
            senderAddress=payload.senderAddress.lower(),
            receiverAddress=payload.receiverAddress.lower(),
            amount=payload.amount,
            nonce=payload.nonce,
            gasLimit=payload.gasLimit,
            gasPrice=payload.gasPrice,
            publicKey=payload.publicKey.lower(),
            signature=payload.signature.lower(),
            status="PENDING",
        )
        db.add(tx)
        await db.commit()
        await db.refresh(tx)

        # 5. Automatically enqueue into local node Mempool
        await MempoolService.add_to_mempool(db, tx)

        logger.info(
            "Node %s verified, accepted, and queued tx: %s (%s -> %s, amount: %s)",
            settings.NODE_ID,
            tx_hash,
            tx.senderAddress,
            tx.receiverAddress,
            tx.amount,
        )
        return tx

    @staticmethod
    async def get_transaction_by_hash(
        db: AsyncSession,
        tx_hash: str,
    ) -> Optional[Transaction]:
        """Fetch transaction record by hash."""
        clean_hash = tx_hash.lower()
        stmt = select(Transaction).where(Transaction.txHash == clean_hash)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()
