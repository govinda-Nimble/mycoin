"""
Transaction validation and mempool ingestion service.

Implements the multi-stage validation pipeline:
1. Sender account existence & active status check
2. Receiver address format & non-identity check
3. Cryptographic public key address derivation verification
4. Deterministic ECDSA secp256k1 signature verification
5. Sequential nonce & live conflict check
6. Spendable balance check (accounting for unconfirmed mempool transactions)
7. Gas limit and gas price range check
8. Duplicate transaction hash check
9. Atomic persistence of Transaction with status=PENDING
10. Creation of MempoolTransaction entry associated with an active network node
"""

from dataclasses import dataclass
import hashlib
import logging
from typing import Any, Dict, Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone
import ecdsa

from common.models import ImmutableRecordError
from common.utils import format_database_constraint_error
from ledger.models import (
    MempoolStatus,
    MempoolTransaction,
    NONCE_FREE_STATUSES,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from network.models import Account, AccountStatus, Blockchain, BlockchainStatus, Node

logger = logging.getLogger(__name__)


class TransactionValidationError(Exception):
    """Raised when a transaction fails any step in the validation pipeline."""

    def __init__(self, message: str, step: str):
        super().__init__(message)
        self.message = message
        self.step = step


@dataclass
class TransactionValidationResult:
    """Encapsulates the result of a successful transaction validation and mempool submission."""

    transaction: Transaction
    mempool_entry: MempoolTransaction
    tx_hash: str
    message: str


def compute_canonical_digest(
    chain_id: int,
    sender_address: str,
    receiver_address: str,
    amount: str,
    nonce: int,
    gas_limit: int,
    gas_price: str,
) -> tuple[str, bytes]:
    """
    Constructs the canonical colon-delimited payload string and returns
    both the canonical string and its SHA-256 digest bytes.
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
    digest = hashlib.sha256(canonical_payload.encode("utf-8")).digest()
    return canonical_payload, digest


def compute_transaction_hash(canonical_digest: bytes, raw_signature_bytes: bytes) -> str:
    """
    Computes deterministic 64-character lowercase hex transaction hash:
    SHA-256(canonical_payload_digest + raw_signature_bytes).
    """
    return hashlib.sha256(canonical_digest + raw_signature_bytes).hexdigest().lower()


def validate_and_enqueue_transaction(
    payload: Dict[str, Any],
    node: Optional[Node] = None,
) -> TransactionValidationResult:
    """
    Executes the full transaction verification pipeline and persists
    the transaction and its mempool entry atomically.

    Args:
        payload: Dictionary containing camelCase fields:
            - senderAddress
            - receiverAddress
            - amount
            - nonce
            - gasLimit
            - gasPrice
            - publicKey
            - signature
        node: Optional target Node instance whose local mempool will ingest the transaction.
            If None, the first active ONLINE node for the blockchain is used.

    Returns:
        TransactionValidationResult on success.

    Raises:
        TransactionValidationError on any validation failure.
    """
    sender_address = str(payload["senderAddress"]).strip().lower()
    receiver_address = str(payload["receiverAddress"]).strip().lower()
    amount_str = str(payload["amount"]).strip()
    amount_int = int(amount_str)
    nonce_int = int(payload["nonce"])
    gas_limit_int = int(payload["gasLimit"])
    gas_price_str = str(payload["gasPrice"]).strip()
    gas_price_int = int(gas_price_str)
    public_key_str = str(payload["publicKey"]).strip().lower()
    signature_str = str(payload["signature"]).strip().lower()

    # -------------------------------------------------------------
    # 0. Active Blockchain Resolution
    # -------------------------------------------------------------
    blockchain = Blockchain.objects.filter(status=BlockchainStatus.ACTIVE).first()
    if not blockchain:
        raise TransactionValidationError(
            "No active blockchain configured. Please initialize the blockchain first.",
            step="BLOCKCHAIN_CHECK",
        )

    # -------------------------------------------------------------
    # 1. Check Sender
    # -------------------------------------------------------------
    sender_account = Account.objects.filter(
        blockchain=blockchain,
        address=sender_address,
    ).first()

    if not sender_account:
        raise TransactionValidationError(
            f"Sender account '{sender_address}' does not exist on active blockchain (Chain ID {blockchain.chainId}).",
            step="CHECK_SENDER",
        )

    if sender_account.status != AccountStatus.ACTIVE:
        raise TransactionValidationError(
            f"Sender account '{sender_address}' is not active (current status: {sender_account.status}).",
            step="CHECK_SENDER",
        )

    # Resolve target Node for local mempool
    if node is None:
        node = Node.objects.filter(blockchain=blockchain, status="ONLINE").first()
        if not node:
            raise TransactionValidationError(
                "Please try again later as there is no active node exists.",
                step="NO_ACTIVE_NODE_EXISTS",
            )
    elif node.blockchain_id != blockchain.id:
        raise TransactionValidationError(
            f"Node '{node.nodeId}' belongs to another blockchain.",
            step="NODE_MISMATCH",
        )

    # -------------------------------------------------------------
    # 2. Check Receiver
    # -------------------------------------------------------------
    if sender_address == receiver_address:
        raise TransactionValidationError(
            "Sender and receiver addresses cannot be identical.",
            step="CHECK_RECEIVER",
        )

    # Resolve receiver account if it exists on-chain
    receiver_account = Account.objects.filter(
        blockchain=blockchain,
        address=receiver_address,
    ).first()

    if receiver_account and receiver_account.status != AccountStatus.ACTIVE:
        raise TransactionValidationError(
            f"Receiver account '{receiver_address}' is not active (current status: {receiver_account.status}).",
            step="CHECK_RECEIVER",
        )

    # -------------------------------------------------------------
    # 3. Verify Public Key (Address Derivation)
    # -------------------------------------------------------------
    clean_pk = public_key_str.removeprefix("04")
    if len(clean_pk) != 128:
        raise TransactionValidationError(
            f"Invalid public key length ({len(clean_pk)} hex characters). Expected 128 raw hex characters.",
            step="VERIFY_PUBLIC_KEY",
        )

    try:
        raw_vk_bytes = bytes.fromhex(clean_pk)
    except ValueError:
        raise TransactionValidationError(
            "Public key contains non-hexadecimal characters.",
            step="VERIFY_PUBLIC_KEY",
        )

    derived_hash = hashlib.sha256(raw_vk_bytes).hexdigest().lower()
    derived_address = "0x" + derived_hash[-40:]

    if derived_address != sender_address:
        raise TransactionValidationError(
            f"Public key does not derive sender address: derived {derived_address}, but got {sender_address}.",
            step="VERIFY_PUBLIC_KEY",
        )

    # -------------------------------------------------------------
    # 4. Verify Cryptographic Signature
    # -------------------------------------------------------------
    clean_sig = signature_str.removeprefix("0x")
    if len(clean_sig) != 128:
        raise TransactionValidationError(
            f"Invalid signature length ({len(clean_sig)} hex characters). Expected 128 hex characters (64 bytes raw r+s).",
            step="VERIFY_SIGNATURE",
        )

    try:
        raw_sig_bytes = bytes.fromhex(clean_sig)
    except ValueError:
        raise TransactionValidationError(
            "Signature contains non-hexadecimal characters.",
            step="VERIFY_SIGNATURE",
        )

    canonical_payload_str, digest = compute_canonical_digest(
        chain_id=blockchain.chainId,
        sender_address=sender_address,
        receiver_address=receiver_address,
        amount=amount_str,
        nonce=nonce_int,
        gas_limit=gas_limit_int,
        gas_price=gas_price_str,
    )

    try:
        vk = ecdsa.VerifyingKey.from_string(raw_vk_bytes, curve=ecdsa.SECP256k1)
        is_valid = vk.verify(
            raw_sig_bytes,
            digest,
            hashfunc=hashlib.sha256,
            sigdecode=ecdsa.util.sigdecode_string,
        )
        if not is_valid:
            raise TransactionValidationError(
                "Cryptographic signature verification returned False.",
                step="VERIFY_SIGNATURE",
            )
    except ecdsa.BadSignatureError:
        raise TransactionValidationError(
            "Invalid cryptographic signature: signature does not match canonical transaction payload.",
            step="VERIFY_SIGNATURE",
        )
    except Exception as exc:
        raise TransactionValidationError(
            f"Signature verification failure: {exc}",
            step="VERIFY_SIGNATURE",
        )

    # -------------------------------------------------------------
    # 5. Check Gas
    # -------------------------------------------------------------
    if gas_limit_int < blockchain.baseTransferGas:
        raise TransactionValidationError(
            f"Gas limit ({gas_limit_int}) is below minimum base transfer gas ({blockchain.baseTransferGas}).",
            step="CHECK_GAS",
        )

    if gas_limit_int > blockchain.maxBlockGas:
        raise TransactionValidationError(
            f"Gas limit ({gas_limit_int}) exceeds blockchain maximum block gas ({blockchain.maxBlockGas}).",
            step="CHECK_GAS",
        )

    if gas_price_int < blockchain.minGasPrice:
        raise TransactionValidationError(
            f"Gas price ({gas_price_int}) is below minimum network gas price ({blockchain.minGasPrice}).",
            step="CHECK_GAS",
        )

    # -------------------------------------------------------------
    # 6. Compute Transaction Hash
    # -------------------------------------------------------------
    tx_hash = compute_transaction_hash(digest, raw_sig_bytes)

    # -------------------------------------------------------------
    # 7. Nonce, Node Mempool Conflict, Balance & Atomic Ingestion
    # -------------------------------------------------------------
    now = timezone.now()
    conflict_rejection: Optional[str] = None

    with transaction.atomic():
        # Lock sender account to serialize concurrent submissions for this sender
        sender_account = Account.objects.select_for_update().get(id=sender_account.id)

        # Evict expired active mempool transactions for this sender on this node
        expired_mtxs = MempoolTransaction.objects.filter(
            node=node,
            transaction__sender=sender_account,
            status=MempoolStatus.ACTIVE,
            expiresAt__lte=now,
        )
        if expired_mtxs.exists():
            expired_tx_ids = list(expired_mtxs.values_list("transaction_id", flat=True))
            expired_mtxs.update(status=MempoolStatus.EXPIRED)
            active_elsewhere = MempoolTransaction.objects.filter(
                transaction_id__in=expired_tx_ids,
                status=MempoolStatus.ACTIVE,
            ).values_list("transaction_id", flat=True)
            Transaction.objects.filter(
                id__in=expired_tx_ids,
                status=TransactionStatus.PENDING,
                block__isnull=True,
            ).exclude(id__in=active_elsewhere).update(status=TransactionStatus.DROPPED)

        # Check account finalized nonce
        if nonce_int < sender_account.nonce:
            raise TransactionValidationError(
                f"Nonce too low: sender account finalized nonce is {sender_account.nonce}, but received {nonce_int}.",
                step="CHECK_NONCE",
            )

        # Check for active mempool transaction for (node, sender, nonce)
        active_mtx = (
            MempoolTransaction.objects.filter(
                node=node,
                transaction__sender=sender_account,
                transaction__nonce=nonce_int,
                status=MempoolStatus.ACTIVE,
                expiresAt__gt=now,
            )
            .select_related("transaction")
            .first()
        )

        if active_mtx:
            # Case 1: Duplicate transaction hash (idempotent gossip or resubmission)
            if active_mtx.transaction.hash == tx_hash:
                raise TransactionValidationError(
                    f"Duplicate transaction: transaction with hash {tx_hash} already recorded on the ledger.",
                    step="CHECK_DUPLICATE_HASH",
                )

            # Case 2: Competing transaction with different hash for the same (node, sender, nonce)
            if gas_price_int > active_mtx.transaction.gasPrice:
                # Fee-bump replacement: deactivate active transaction in this node's mempool
                old_mtx = active_mtx
                old_mtx.status = MempoolStatus.REPLACED
                old_mtx.save(update_fields=["status", "updatedAt"])
                # If old transaction is not active in any other node's mempool, mark it DROPPED
                if not MempoolTransaction.objects.filter(
                    transaction=old_mtx.transaction, status=MempoolStatus.ACTIVE
                ).exists():
                    Transaction.objects.filter(
                        id=old_mtx.transaction_id, status=TransactionStatus.PENDING
                    ).update(status=TransactionStatus.DROPPED)
            else:
                # Lower or equal fee: keep existing active transaction in node mempool.
                # Retain the competing signed transaction in permanent storage.
                competing_tx, _ = Transaction.objects.get_or_create(
                    blockchain=blockchain,
                    hash=tx_hash,
                    defaults={
                        "sender": sender_account,
                        "receiverAddress": receiver_address,
                        "receiver": receiver_account,
                        "txType": TransactionType.TRANSFER,
                        "amount": amount_int,
                        "nonce": nonce_int,
                        "gasLimit": gas_limit_int,
                        "gasPrice": gas_price_int,
                        "publicKey": "04" + clean_pk,
                        "signature": clean_sig,
                        "status": TransactionStatus.DROPPED,
                    },
                )
                MempoolTransaction.objects.get_or_create(
                    node=node,
                    transaction=competing_tx,
                    defaults={
                        "priority": gas_price_int,
                        "arrivalTime": now,
                        "expiresAt": now + timezone.timedelta(hours=2),
                        "status": MempoolStatus.REPLACED,
                    },
                )
                conflict_rejection = (
                    f"Nonce conflict: an active transaction ({active_mtx.transaction.hash[:12]}...) with nonce {nonce_int} and higher or equal gas price ({active_mtx.transaction.gasPrice} >= {gas_price_int}) already exists in this node's mempool."
                )

        if not conflict_rejection:
            # Check for sequential nonce gap on this node
            active_nonces = set(
                MempoolTransaction.objects.filter(
                    node=node,
                    transaction__sender=sender_account,
                    status=MempoolStatus.ACTIVE,
                    expiresAt__gt=now,
                ).values_list("transaction__nonce", flat=True)
            )
            missing_nonces = [n for n in range(sender_account.nonce, nonce_int) if n not in active_nonces]
            if missing_nonces:
                expected_next = min(missing_nonces)
                raise TransactionValidationError(
                    f"Nonce gap detected: expected next nonce {expected_next}, but received {nonce_int}.",
                    step="CHECK_NONCE",
                )

            # Check Balance (funds committed by other active transactions on this node)
            gas_fee = gas_limit_int * gas_price_int
            total_cost = amount_int + gas_fee

            active_committed = (
                MempoolTransaction.objects.filter(
                    node=node,
                    transaction__sender=sender_account,
                    status=MempoolStatus.ACTIVE,
                    expiresAt__gt=now,
                )
                .exclude(transaction__nonce=nonce_int)
                .aggregate(
                    total=models.Sum(
                        models.F("transaction__amount")
                        + (models.F("transaction__gasLimit") * models.F("transaction__gasPrice"))
                    )
                )["total"]
                or 0
            )

            available_balance = sender_account.balance - active_committed
            if available_balance < total_cost:
                raise TransactionValidationError(
                    f"Insufficient balance: sender on-chain balance is {sender_account.balance:,} units (available: {available_balance:,} units), "
                    f"but this transaction requires {total_cost:,} units ({amount_int:,} transfer + {gas_fee:,} max fee).",
                    step="CHECK_BALANCE",
                )

            try:
                # Check duplicate hash against finalized/failed transactions
                existing_tx = Transaction.objects.filter(blockchain=blockchain, hash=tx_hash).first()
                if existing_tx:
                    if existing_tx.status in [TransactionStatus.FINALIZED, TransactionStatus.FAILED]:
                        raise TransactionValidationError(
                            f"Duplicate transaction: transaction with hash {tx_hash} already recorded on the ledger in status '{existing_tx.status}'.",
                            step="CHECK_DUPLICATE_HASH",
                        )
                    tx = existing_tx
                    if tx.status in [TransactionStatus.REPLACED, TransactionStatus.DROPPED]:
                        tx.status = TransactionStatus.PENDING
                        tx.save(update_fields=["status", "updatedAt"])
                else:
                    tx = Transaction.objects.create(
                        hash=tx_hash,
                        blockchain=blockchain,
                        sender=sender_account,
                        receiverAddress=receiver_address,
                        receiver=receiver_account,
                        txType=TransactionType.TRANSFER,
                        amount=amount_int,
                        nonce=nonce_int,
                        gasLimit=gas_limit_int,
                        gasPrice=gas_price_int,
                        publicKey="04" + clean_pk,
                        signature=clean_sig,
                        status=TransactionStatus.PENDING,
                    )
                    tx.full_clean()

                mempool_entry, _ = MempoolTransaction.objects.update_or_create(
                    node=node,
                    transaction=tx,
                    defaults={
                        "priority": gas_price_int,
                        "arrivalTime": now,
                        "expiresAt": now + timezone.timedelta(hours=2),
                        "status": MempoolStatus.ACTIVE,
                    },
                )
                mempool_entry.full_clean()
            except (IntegrityError, DjangoValidationError, ImmutableRecordError) as exc:
                clean_err = format_database_constraint_error(exc)
                raise TransactionValidationError(clean_err, step="CHECK_CONSTRAINTS") from exc

    if conflict_rejection:
        raise TransactionValidationError(conflict_rejection, step="CHECK_NONCE")

    logger.info(
        "Transaction %s validated and queued into mempool of node %s (sender: %s, amount: %d, priority: %d)",
        tx_hash[:12],
        node.nodeId,
        sender_address,
        amount_int,
        gas_price_int,
    )

    return TransactionValidationResult(
        transaction=tx,
        mempool_entry=mempool_entry,
        tx_hash="0x" + tx_hash,
        message="Transaction validated successfully and enqueued into mempool.",
    )

