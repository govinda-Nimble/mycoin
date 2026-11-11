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

from django.db import models, transaction
from django.utils import timezone
import ecdsa

from ledger.models import (
    MempoolStatus,
    MempoolTransaction,
    NONCE_FREE_STATUSES,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from network.models import Blockchain, BlockchainStatus, Node
from wallets.models import Account, AccountStatus

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


def validate_and_enqueue_transaction(payload: Dict[str, Any]) -> TransactionValidationResult:
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

    if not receiver_account:
        raise TransactionValidationError(
            f"Receiver account '{receiver_address}' does not exist on active blockchain (Chain ID {blockchain.chainId}).",
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
    # 5. Check Nonce
    # -------------------------------------------------------------
    if nonce_int < sender_account.nonce:
        raise TransactionValidationError(
            f"Nonce too low: sender account finalized nonce is {sender_account.nonce}, but received {nonce_int}.",
            step="CHECK_NONCE",
        )

    # Check for live nonce conflicts
    existing_nonce_tx = Transaction.objects.filter(
        sender=sender_account,
        nonce=nonce_int,
    ).exclude(status__in=NONCE_FREE_STATUSES).first()

    if existing_nonce_tx:
        raise TransactionValidationError(
            f"Nonce conflict: a live transaction ({existing_nonce_tx.hash[:12]}...) with nonce {nonce_int} already exists in status '{existing_nonce_tx.status}'.",
            step="CHECK_NONCE",
        )

    # Check sequential nonce gap
    pending_count = Transaction.objects.filter(
        sender=sender_account,
        status=TransactionStatus.PENDING,
    ).count()
    expected_nonce = sender_account.nonce + pending_count

    if nonce_int > expected_nonce:
        raise TransactionValidationError(
            f"Nonce gap detected: expected next nonce {expected_nonce}, but received {nonce_int}.",
            step="CHECK_NONCE",
        )

    # -------------------------------------------------------------
    # 6. Check Balance
    # -------------------------------------------------------------
    gas_fee = gas_limit_int * gas_price_int
    total_cost = amount_int + gas_fee

    # Calculate funds already locked by earlier pending transactions from this sender
    pending_committed = Transaction.objects.filter(
        sender=sender_account,
        status=TransactionStatus.PENDING,
    ).aggregate(
        total=models.Sum(models.F("amount") + (models.F("gasLimit") * models.F("gasPrice")))
    )["total"] or 0

    available_balance = sender_account.balance - pending_committed

    if available_balance < total_cost:
        multiplier = 10 ** blockchain.decimals
        raise TransactionValidationError(
            f"Insufficient balance: sender on-chain balance is {sender_account.balance:,} units (available: {available_balance:,} units), "
            f"but this transaction requires {total_cost:,} units ({amount_int:,} transfer + {gas_fee:,} max fee).",
            step="CHECK_BALANCE",
        )

    # -------------------------------------------------------------
    # 7. Check Gas
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
    # 8. Check Duplicate Hash
    # -------------------------------------------------------------
    tx_hash = compute_transaction_hash(digest, raw_sig_bytes)
    if Transaction.objects.filter(hash=tx_hash).exists():
        raise TransactionValidationError(
            f"Duplicate transaction: transaction with hash {tx_hash} already recorded on the ledger.",
            step="CHECK_DUPLICATE_HASH",
        )

    # -------------------------------------------------------------
    # 9. Save Transaction & 10. Create MempoolTransaction (Atomic)
    # -------------------------------------------------------------
    with transaction.atomic():
        # Persist verified Transaction with status=PENDING
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

        # Resolve or auto-seed active node for the mempool entry
        node = Node.objects.filter(blockchain=blockchain, status="ONLINE").first()
        if not node:
            raise TransactionValidationError(
                f"Please try again later as there is no active node exists.",
                step="NO_ACTIVE_NODE_EXISTS",
            )
        # if not node:
        #     node = Node.objects.filter(blockchain=blockchain).first()
        # if not node:
        #     from network.services.node_seeder import seed_validator_node
        #     seed_res = seed_validator_node(node_id="myc-val-node-001", node_status="ONLINE")
        #     node = seed_res.node

        now = timezone.now()
        mempool_entry = MempoolTransaction.objects.create(
            transaction=tx,
            node=node,
            priority=gas_price_int,
            arrivalTime=now,
            expiresAt=now + timezone.timedelta(hours=2),
            status=MempoolStatus.ACTIVE,
        )
        mempool_entry.full_clean()

    logger.info(
        "Transaction %s validated and queued into mempool (sender: %s, amount: %d, priority: %d)",
        tx_hash[:12],
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

