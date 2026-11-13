"""Blockchain and Account models for the chain app."""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from common.models import BaseModel, address_validator, amount_field, check


class BlockchainStatus(models.TextChoices):
    INITIALIZING = "INITIALIZING", "Initializing"
    ACTIVE = "ACTIVE", "Active"
    HALTED = "HALTED", "Halted"


class AccountType(models.TextChoices):
    EOA = "EOA", "Externally owned account"
    CONTRACT = "CONTRACT", "Contract account"


class SystemAccountType(models.TextChoices):
    TREASURY = "TREASURY", "Treasury"
    VALIDATOR_RESERVE = "VALIDATOR_RESERVE", "Validator Reserve"
    DEVELOPMENT_RESERVE = "DEVELOPMENT_RESERVE", "Development Reserve"


class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    FROZEN = "FROZEN", "Frozen"
    CLOSED = "CLOSED", "Closed"


class Blockchain(BaseModel):
    """A chain (e.g. mainnet / testnet). Root of the schema; holds protocol configuration."""

    Status = BlockchainStatus

    chainId = models.PositiveIntegerField(
        unique=True,
        help_text="Network identifier, also used in transaction hashing for replay protection.",
        error_messages={"unique": "A blockchain with this chain ID already exists."},
    )
    name = models.CharField(max_length=64, unique=True)
    symbol = models.CharField(max_length=10, default="MYC", help_text="Native currency symbol.")
    decimals = models.PositiveSmallIntegerField(
        default=8,
        validators=[MaxValueValidator(18)],
        help_text="1 coin = 10**decimals smallest units. 8 keeps balances inside BigIntegerField.",
    )
    blockTimeSeconds = models.PositiveIntegerField(default=5, validators=[MinValueValidator(1)])
    maxBlockGas = amount_field("Maximum total gas per block.", default=30_000_000)
    minGasPrice = amount_field("Minimum accepted gas price (smallest units per gas).", default=1)
    baseTransferGas = amount_field("Fixed gas cost of a native transfer.", default=21_000)
    minValidatorStake = amount_field(
        "Minimum total stake (smallest units) for a validator to be eligible.",
        default=1_000 * 10**8,
    )
    unbondingBlocks = models.PositiveIntegerField(
        default=1_000, help_text="Blocks an unstaked amount stays locked before withdrawal."
    )
    blockReward = amount_field("Protocol block reward in smallest units.", default=5 * 10**8)
    finalityNumerator = models.PositiveSmallIntegerField(
        default=2, help_text="Finality needs voting power strictly above numerator/denominator."
    )
    finalityDenominator = models.PositiveSmallIntegerField(default=3)
    status = models.CharField(
        max_length=16, choices=BlockchainStatus.choices, default=BlockchainStatus.INITIALIZING
    )
    latestFinalizedBlock = models.ForeignKey(
        "ledger.Block",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="finalized_tip_of",
        help_text="Current finalized tip. Null until genesis is finalized.",
    )

    class Meta:
        constraints = [
            check(Q(decimals__lte=18), "chain_blockchain_decimals_max_18"),
            check(
                Q(
                    blockTimeSeconds__gt=0,
                    maxBlockGas__gt=0,
                    baseTransferGas__gt=0,
                    minGasPrice__gt=0,
                    minValidatorStake__gt=0,
                    blockReward__gte=0,
                ),
                "chain_blockchain_config_positive",
            ),
            check(
                Q(finalityNumerator__gt=0, finalityNumerator__lt=F("finalityDenominator")),
                "chain_blockchain_finality_fraction",
            ),
        ]

    def __str__(self):
        return f"{self.name} (chain {self.chainId})"

    def clean(self):
        super().clean()
        tip = self.latestFinalizedBlock
        if tip is not None:
            if tip.blockchain_id != self.id:
                raise ValidationError({"latestFinalizedBlock": "Block belongs to another blockchain."})
            if tip.status != "FINALIZED":
                raise ValidationError({"latestFinalizedBlock": "Block is not finalized."})


class Account(BaseModel):
    """On-chain account state. Balance and nonce change ONLY when a block is finalized."""

    Type = AccountType
    Status = AccountStatus

    blockchain = models.ForeignKey(Blockchain, on_delete=models.PROTECT, related_name="accounts")
    systemAccountType = models.CharField(
        max_length=30,
        choices=SystemAccountType.choices,
        null=True,
        blank=True,
        help_text="Identifies the purpose of a system account."
    )
    address = models.CharField(
        max_length=42,
        validators=[address_validator],
        error_messages={"unique": "This address already exists on this blockchain."},
    )
    accountType = models.CharField(max_length=16, choices=AccountType.choices, default=AccountType.EOA)
    balance = amount_field("Finalized spendable balance in smallest units.", default=0)
    nonce = models.BigIntegerField(
        default=0,
        help_text="Next expected finalized transaction nonce (sequential, starts at 0).",
    )
    status = models.CharField(max_length=16, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    creationBlock = models.ForeignKey(
        "ledger.Block",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_accounts",
        help_text="Block that created the account. Null only for genesis accounts.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blockchain", "address"], name="chain_account_unique_address"),
            check(Q(balance__gte=0), "chain_account_balance_non_negative"),
            check(Q(nonce__gte=0), "chain_account_nonce_non_negative"),
        ]
        indexes = [models.Index(fields=["blockchain", "status"])]

    def __str__(self):
        return self.address
