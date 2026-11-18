"""Ledger models: Block, Transaction, BlockTransaction, TransactionReceipt, TransactionEvent, MempoolTransaction.

Rules enforced here at database level (constraints) or model level (clean/save). Business rules such as the
transaction state machine, signature verification and balance checks belong to the domain/application layers.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from common.models import (
    GENESIS_PREVIOUS_HASH,
    BaseModel,
    ImmutableRecordError,
    address_validator,
    amount_field,
    check,
    hash_validator,
    hex_validator,
)


class BlockStatus(models.TextChoices):
    PROPOSED = "PROPOSED", "Proposed"
    FINALIZED = "FINALIZED", "Finalized"
    REJECTED = "REJECTED", "Rejected"


class TransactionType(models.TextChoices):
    REG_BONUS = "REG_BONUS", "Registration Bonus"
    TRANSFER = "TRANSFER", "Native transfer"
    STAKE = "STAKE", "Stake"
    UNSTAKE = "UNSTAKE", "Unstake"
    WITHDRAW_STAKE = "WITHDRAW_STAKE", "Withdraw unbonded stake"


class TransactionStatus(models.TextChoices):
    CREATED = "CREATED", "Created"
    SIGNED = "SIGNED", "Signed"
    VALIDATED = "VALIDATED", "Validated"
    PENDING = "PENDING", "Pending (in mempool)"
    INCLUDED = "INCLUDED", "Included in a proposed block"
    FINALIZED = "FINALIZED", "Finalized"
    FAILED = "FAILED", "Failed (executed in a finalized block)"
    REJECTED = "REJECTED", "Rejected (invalid before inclusion)"
    DROPPED = "DROPPED", "Dropped (evicted/expired)"
    REPLACED = "REPLACED", "Replaced"


# Statuses in which a transaction is not part of any block.
NO_BLOCK_STATUSES = ["CREATED", "SIGNED", "VALIDATED", "PENDING", "REJECTED", "DROPPED", "REPLACED"]
# Statuses in which a transaction may still be unsigned.
UNSIGNED_ALLOWED_STATUSES = ["CREATED", "REJECTED", "DROPPED", "REPLACED"]
# Statuses that do not occupy a (sender, nonce) slot.
NONCE_FREE_STATUSES = ["REJECTED", "DROPPED", "FAILED", "REPLACED"]


class ReceiptStatus(models.TextChoices):
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"


class EventType(models.TextChoices):
    TRANSFER = "TRANSFER", "Transfer"
    FEE_PAID = "FEE_PAID", "Fee paid"
    ACCOUNT_CREATED = "ACCOUNT_CREATED", "Account created"
    STAKE = "STAKE", "Stake"
    UNSTAKE = "UNSTAKE", "Unstake"
    STAKE_WITHDRAWN = "STAKE_WITHDRAWN", "Stake withdrawn"


class MempoolStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INCLUDED = "INCLUDED", "Included in a block"
    EVICTED = "EVICTED", "Evicted"
    EXPIRED = "EXPIRED", "Expired"
    REPLACED = "REPLACED", "Replaced"


class Block(BaseModel):
    """A block. Finalized blocks are immutable (guarded in save()/delete(); DB trigger planned later).

    ``transactionCount`` and ``gasUsed`` are header facts that must match the BlockTransaction rows;
    the application layer checks this when the block is built or validated.
    """

    Status = BlockStatus

    blockchain = models.ForeignKey("chain.Blockchain", on_delete=models.PROTECT, related_name="blocks")
    height = models.PositiveBigIntegerField(help_text="Sequential height. Genesis = 0.")
    blockHash = models.CharField(
        max_length=64,
        validators=[hash_validator],
        help_text="Hash of the canonical block header (computed in the domain layer).",
        error_messages={"unique": "A block with this hash already exists on this blockchain."},
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        help_text="Previous block. Null only for genesis.",
    )
    previousHash = models.CharField(
        max_length=64, validators=[hash_validator], help_text="Parent hash; 64 zeros for genesis."
    )
    merkleRoot = models.CharField(max_length=64, validators=[hash_validator])
    stateRoot = models.CharField(
        max_length=64,
        blank=True,
        validators=[hash_validator],
        help_text="Placeholder until a state trie exists.",
    )
    timestamp = models.DateTimeField()
    proposer = models.ForeignKey(
        "staking.Validator",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposed_blocks",
        help_text="Validator that proposed the block. Null only for genesis.",
    )
    status = models.CharField(max_length=16, choices=BlockStatus.choices, default=BlockStatus.PROPOSED)
    transactionCount = models.PositiveIntegerField(default=0)
    gasUsed = amount_field("Total gas used by the block's transactions.", default=0)
    blockReward = amount_field("Protocol reward minted for this block.", default=0)
    epoch = models.PositiveIntegerField(default=0, help_text="Consensus metadata: validator-set epoch.")
    round = models.PositiveIntegerField(default=0, help_text="Consensus metadata: proposal round at this height.")
    proposerSignature = models.CharField(max_length=200, blank=True, validators=[hex_validator])
    finalizedAt = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blockchain", "blockHash"], name="chain_block_unique_hash"),
            # Competing proposals may share a height; only ONE block per height may be finalized.
            models.UniqueConstraint(
                fields=["blockchain", "height"],
                condition=Q(status="FINALIZED"),
                name="chain_block_unique_finalized_height",
            ),
            check(
                Q(height=0, parent__isnull=True, proposer__isnull=True)
                | Q(height__gt=0, parent__isnull=False, proposer__isnull=False),
                "chain_block_genesis_rule",
            ),
            check(~Q(status="FINALIZED") | Q(finalizedAt__isnull=False), "chain_block_finalized_has_timestamp"),
            check(Q(gasUsed__gte=0, blockReward__gte=0), "chain_block_amounts_non_negative"),
        ]
        indexes = [
            models.Index(fields=["blockchain", "height"]),
            models.Index(fields=["blockchain", "status"]),
        ]

    def __str__(self):
        return f"Block #{self.height} {self.blockHash[:10]}"

    def _stored_status(self):
        return (
            type(self)._default_manager.filter(pk=self.pk).values_list("status", flat=True).first()
        )

    def save(self, *args, **kwargs):
        if not self._state.adding and self._stored_status() == BlockStatus.FINALIZED:
            raise ImmutableRecordError("Finalized blocks cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self._stored_status() == BlockStatus.FINALIZED:
            raise ImmutableRecordError("Finalized blocks cannot be deleted.")
        return super().delete(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if self.height == 0 and self.previousHash != GENESIS_PREVIOUS_HASH:
            errors["previousHash"] = "Genesis block must use the all-zero previous hash."
        if self.parent_id:
            parent = self.parent
            if parent.blockchain_id != self.blockchain_id:
                errors["parent"] = "Parent block belongs to another blockchain."
            if parent.blockHash != self.previousHash:
                errors["previousHash"] = "Must equal the parent block's hash."
            if self.height is not None and parent.height + 1 != self.height:
                errors["height"] = "Height must be parent height + 1."
        if self.proposer_id and self.proposer.account.blockchain_id != self.blockchain_id:
            errors["proposer"] = "Proposer belongs to another blockchain."
        if errors:
            raise ValidationError(errors)


class Transaction(BaseModel):
    """A signed state-change request. Pending transactions never touch finalized balances."""

    Type = TransactionType
    Status = TransactionStatus

    hash = models.CharField(
        max_length=64,
        unique=True,
        validators=[hash_validator],
        help_text="Hash of the canonical, signed transaction payload.",
        error_messages={"unique": "A transaction with this hash already exists."},
    )
    blockchain = models.ForeignKey("chain.Blockchain", on_delete=models.PROTECT, related_name="transactions")
    sender = models.ForeignKey("chain.Account", on_delete=models.PROTECT, related_name="sent_transactions")
    receiverAddress = models.CharField(max_length=42, validators=[address_validator])
    receiver = models.ForeignKey(
        "chain.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="received_transactions",
        help_text="Filled at execution; the receiver account may not exist before then.",
    )
    txType = models.CharField(max_length=16, choices=TransactionType.choices, default=TransactionType.TRANSFER)
    amount = amount_field("Amount in smallest units. Must be > 0.")
    nonce = models.BigIntegerField(help_text="Sender's sequential nonce for this transaction.")
    gasLimit = amount_field("Maximum gas the sender allows.")
    gasPrice = amount_field("Price per gas unit in smallest units.")
    feePaid = amount_field(
        "Actual fee charged (gasUsed * effective gas price). Set at finalization.", null=True, blank=True
    )
    signature = models.CharField(max_length=200, blank=True, validators=[hex_validator])
    publicKey = models.CharField(
        max_length=130,
        blank=True,
        validators=[hex_validator],
        help_text="Signer public key; its hash must equal the sender address (domain check).",
    )
    status = models.CharField(
        max_length=16, choices=TransactionStatus.choices, default=TransactionStatus.CREATED
    )
    block = models.ForeignKey(
        "ledger.Block",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="included_transactions",
        help_text="Denormalized convenience copy; BlockTransaction is the source of truth.",
    )

    class Meta:
        constraints = [
            check(Q(amount__gt=0), "chain_tx_amount_positive"),
            check(Q(gasLimit__gt=0), "chain_tx_gas_limit_positive"),
            check(Q(nonce__gte=0), "chain_tx_nonce_non_negative"),
            check(Q(gasPrice__gte=0), "chain_tx_gas_price_non_negative"),
            check(
                Q(feePaid__isnull=True)
                | Q(feePaid__gte=0, feePaid__lte=F("gasLimit") * F("gasPrice")),
                "chain_tx_fee_within_gas_limit",
            ),
            check(
                Q(feePaid__isnull=True) | Q(status__in=["FINALIZED", "FAILED"]),
                "chain_tx_fee_only_when_executed",
            ),
            check(
                Q(status__in=NO_BLOCK_STATUSES, block__isnull=True)
                | (~Q(status__in=NO_BLOCK_STATUSES) & Q(block__isnull=False)),
                "chain_tx_block_matches_status",
            ),
            check(
                Q(status__in=UNSIGNED_ALLOWED_STATUSES) | ~Q(signature=""),
                "chain_tx_signature_required",
            ),
            check(Q(signature="") | ~Q(publicKey=""), "chain_tx_public_key_with_signature"),
        ]
        indexes = [
            models.Index(fields=["blockchain", "status"]),
            models.Index(fields=["sender", "nonce"]),
            models.Index(fields=["receiverAddress"]),
        ]

    def __str__(self):
        return f"Tx {self.hash[:10]} ({self.status})"

    def clean(self):
        super().clean()
        errors = {}
        if self.sender_id and self.sender.blockchain_id != self.blockchain_id:
            errors["sender"] = "Sender account belongs to another blockchain."
        if self.receiver_id:
            if self.receiver.blockchain_id != self.blockchain_id:
                errors["receiver"] = "Receiver account belongs to another blockchain."
            elif self.receiver.address != self.receiverAddress:
                errors["receiver"] = "Receiver account address does not match receiverAddress."
        if self.block_id and self.block.blockchain_id != self.blockchain_id:
            errors["block"] = "Block belongs to another blockchain."
        if (
            self.feePaid is not None
            and self.gasLimit is not None
            and self.gasPrice is not None
            and self.feePaid > self.gasLimit * self.gasPrice
        ):
            errors["feePaid"] = "Fee cannot exceed gasLimit * gasPrice."
        if errors:
            raise ValidationError(errors)


class BlockTransaction(BaseModel):
    """Ordered membership of a transaction in a block (source of truth).

    Rows of a REJECTED proposal are deleted by the application layer (and Transaction.block cleared) so
    the transactions can be proposed again. Rows of a FINALIZED block can no longer change.
    """

    block = models.ForeignKey(Block, on_delete=models.PROTECT, related_name="block_transactions")
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="block_entry",
        error_messages={"unique": "This transaction is already included in a block."},
    )
    txIndex = models.PositiveIntegerField(help_text="Position inside the block, starting at 0.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["block", "txIndex"], name="chain_blocktx_unique_index"),
        ]

    def __str__(self):
        return f"{self.block_id}[{self.txIndex}]"

    def save(self, *args, **kwargs):
        if self.block.status == BlockStatus.FINALIZED:
            raise ImmutableRecordError("Transactions of a finalized block cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.block.status == BlockStatus.FINALIZED:
            raise ImmutableRecordError("Transactions of a finalized block cannot be removed.")
        return super().delete(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.block_id and self.transaction_id and self.block.blockchain_id != self.transaction.blockchain_id:
            raise ValidationError("Block and transaction belong to different blockchains.")


class TransactionReceipt(BaseModel):
    """Execution outcome, created when the containing block is finalized."""

    Status = ReceiptStatus

    transaction = models.OneToOneField(Transaction, on_delete=models.PROTECT, related_name="receipt")
    block = models.ForeignKey(Block, on_delete=models.PROTECT, related_name="receipts")
    status = models.CharField(max_length=16, choices=ReceiptStatus.choices)
    gasUsed = amount_field("Gas actually consumed.")
    effectiveGasPrice = amount_field("Gas price actually charged.")
    resultCode = models.CharField(max_length=64, blank=True)
    resultMessage = models.TextField(blank=True)

    class Meta:
        constraints = [
            check(Q(gasUsed__gte=0, effectiveGasPrice__gte=0), "chain_receipt_amounts_non_negative"),
        ]

    def __str__(self):
        return f"Receipt {self.transaction_id} {self.status}"

    def clean(self):
        super().clean()
        errors = {}
        tx = self.transaction if self.transaction_id else None
        if tx is not None:
            if self.gasUsed is not None and self.gasUsed > tx.gasLimit:
                errors["gasUsed"] = "Gas used cannot exceed the transaction gas limit."
            if self.effectiveGasPrice is not None and self.effectiveGasPrice > tx.gasPrice:
                errors["effectiveGasPrice"] = "Effective gas price cannot exceed the transaction gas price."
            if self.block_id and tx.block_id != self.block_id:
                errors["block"] = "Receipt block must be the block the transaction is included in."
        if errors:
            raise ValidationError(errors)


class TransactionEvent(BaseModel):
    """Log entry emitted while executing a transaction (the only JSON field in the schema)."""

    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="events")
    eventType = models.CharField(max_length=24, choices=EventType.choices)
    eventIndex = models.PositiveIntegerField(help_text="Order of the event within the transaction.")
    eventData = models.JSONField(default=dict, help_text="Variable payload, depends on event_type.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["transaction", "eventIndex"], name="chain_txevent_unique_index"),
        ]
        indexes = [models.Index(fields=["eventType"])]

    def __str__(self):
        return f"{self.eventType}#{self.eventIndex}"


class MempoolTransaction(BaseModel):
    """A pending transaction as held by one node. Temporary; never affects finalized balances."""

    Status = MempoolStatus

    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="mempool_entries")
    node = models.ForeignKey("network.Node", on_delete=models.PROTECT, related_name="mempool_entries")
    priority = amount_field("Ordering key, normally the gas price. Higher is selected first.", default=0)
    arrivalTime = models.DateTimeField(default=timezone.now)
    expiresAt = models.DateTimeField()
    status = models.CharField(max_length=16, choices=MempoolStatus.choices, default=MempoolStatus.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["node", "transaction"], name="chain_mempool_unique_node_tx"),
            check(Q(priority__gte=0), "chain_mempool_priority_non_negative"),
            check(Q(expiresAt__gt=F("arrivalTime")), "chain_mempool_expiry_after_arrival"),
        ]
        indexes = [
            models.Index(fields=["node", "status", "-priority"]),
            models.Index(fields=["expiresAt"]),
        ]

    def __str__(self):
        return f"Mempool {self.transaction_id} @ {self.node_id}"

    def clean(self):
        super().clean()
        if self.node_id and self.transaction_id and self.node.blockchain_id != self.transaction.blockchain_id:
            raise ValidationError("Node and transaction belong to different blockchains.")
