"""Proof-of-Stake models: Validator, Stake, BlockVote, ValidatorReward, SlashingRecord.

Proposer selection, vote counting, reward calculation and slashing execution are NOT here: they are domain
services added in a later phase. These models only store their inputs and results.
"""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from .base import BaseModel, amount_field, check, hash_validator, hex_validator


class ValidatorStatus(models.TextChoices):
    PENDING = "PENDING", "Pending activation"
    ACTIVE = "ACTIVE", "Active"
    JAILED = "JAILED", "Jailed"
    UNBONDING = "UNBONDING", "Unbonding"
    EXITED = "EXITED", "Exited"


class StakeStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    UNBONDING = "UNBONDING", "Unbonding"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


class VoteType(models.TextChoices):
    APPROVE = "APPROVE", "Approve"
    REJECT = "REJECT", "Reject"


class RewardType(models.TextChoices):
    BLOCK_REWARD = "BLOCK_REWARD", "Block reward"
    TX_FEES = "TX_FEES", "Transaction fees"


class RewardStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"


class OffenceType(models.TextChoices):
    DOUBLE_SIGN = "DOUBLE_SIGN", "Double signing"
    INVALID_BLOCK = "INVALID_BLOCK", "Proposed invalid block"
    DOWNTIME = "DOWNTIME", "Downtime"


class Validator(BaseModel):
    """A staked participant allowed to propose and vote. One validator per account."""

    Status = ValidatorStatus

    account = models.OneToOneField("chain.Account", on_delete=models.PROTECT, related_name="validator")
    public_key = models.CharField(
        max_length=130,
        unique=True,
        validators=[hex_validator],
        help_text="Key used to verify this validator's proposals and votes.",
        error_messages={"unique": "A validator with this public key already exists."},
    )
    status = models.CharField(max_length=16, choices=ValidatorStatus.choices, default=ValidatorStatus.PENDING)
    total_stake = amount_field(
        "Denormalized sum of active stakes. Updated in the same atomic block as the Stake rows.", default=0
    )
    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Share of rewards kept by the validator (0-100).",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    last_proposed_block = models.ForeignKey(
        "chain.Block",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="last_proposed_by",
    )
    last_active_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            check(Q(total_stake__gte=0), "chain_validator_stake_non_negative"),
            check(
                Q(commission_percent__gte=0, commission_percent__lte=100),
                "chain_validator_commission_range",
            ),
            check(~Q(status="ACTIVE") | Q(activated_at__isnull=False), "chain_validator_active_has_time"),
        ]
        indexes = [models.Index(fields=["status", "-total_stake"])]

    def __str__(self):
        return f"Validator {self.account_id} ({self.status})"

    def clean(self):
        super().clean()
        if self.account_id and self.account.account_type != "EOA":
            raise ValidationError({"account": "Only externally owned accounts can be validators."})


class Stake(BaseModel):
    """One staking action by an account towards a validator (one row per STAKE transaction).

    Lock rules are in blocks, not wall-clock time, so they are deterministic:
    * ``lock_period_blocks``: minimum blocks the stake stays staked before unstaking is allowed.
    * ``unlock_height``: set when unstaking starts; funds are withdrawable from this height on.
    """

    Status = StakeStatus

    validator = models.ForeignKey(Validator, on_delete=models.PROTECT, related_name="stakes")
    staker_account = models.ForeignKey("chain.Account", on_delete=models.PROTECT, related_name="stakes")
    amount = amount_field("Staked amount in smallest units. Must be > 0.")
    status = models.CharField(max_length=16, choices=StakeStatus.choices, default=StakeStatus.ACTIVE)
    staked_at_height = models.PositiveBigIntegerField(help_text="Finalized height at which the stake started.")
    staked_at = models.DateTimeField(default=timezone.now)
    lock_period_blocks = models.PositiveIntegerField(default=0)
    unlock_height = models.PositiveBigIntegerField(null=True, blank=True)
    unstake_requested_at = models.DateTimeField(null=True, blank=True)
    stake_transaction = models.OneToOneField(
        "chain.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stake_record",
        help_text="STAKE transaction. Null for genesis stakes.",
    )
    unstake_transaction = models.OneToOneField(
        "chain.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="unstake_record",
    )

    class Meta:
        constraints = [
            check(Q(amount__gt=0), "chain_stake_amount_positive"),
            check(
                Q(status="ACTIVE") | Q(unlock_height__isnull=False, unstake_requested_at__isnull=False),
                "chain_stake_unbonding_needs_unlock",
            ),
            check(
                Q(unlock_height__isnull=True) | Q(unlock_height__gte=F("staked_at_height")),
                "chain_stake_unlock_after_stake",
            ),
        ]
        indexes = [
            models.Index(fields=["validator", "status"]),
            models.Index(fields=["staker_account", "status"]),
        ]

    def __str__(self):
        return f"Stake {self.amount} -> {self.validator_id} ({self.status})"

    def clean(self):
        super().clean()
        if (
            self.validator_id
            and self.staker_account_id
            and self.validator.account.blockchain_id != self.staker_account.blockchain_id
        ):
            raise ValidationError("Validator and staker account belong to different blockchains.")


class BlockVote(BaseModel):
    """A validator's vote on a proposed block. Voting power is a snapshot taken at vote time."""

    Type = VoteType

    block = models.ForeignKey("chain.Block", on_delete=models.PROTECT, related_name="votes")
    validator = models.ForeignKey(Validator, on_delete=models.PROTECT, related_name="votes")
    vote_type = models.CharField(max_length=16, choices=VoteType.choices)
    voting_power = amount_field("Validator's voting power (stake) at vote time. Must be > 0.")
    signature = models.CharField(max_length=200, validators=[hex_validator])
    voted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["block", "validator"], name="chain_vote_one_per_validator"),
            check(Q(voting_power__gt=0), "chain_vote_power_positive"),
        ]
        indexes = [models.Index(fields=["block", "vote_type"])]

    def __str__(self):
        return f"{self.vote_type} by {self.validator_id} on {self.block_id}"

    def clean(self):
        super().clean()
        if self.block_id and self.validator_id and self.block.blockchain_id != self.validator.account.blockchain_id:
            raise ValidationError("Block and validator belong to different blockchains.")


class ValidatorReward(BaseModel):
    """Reward earned by a validator for a block. Paid (credited to the account) at finalization."""

    Type = RewardType
    Status = RewardStatus

    validator = models.ForeignKey(Validator, on_delete=models.PROTECT, related_name="rewards")
    block = models.ForeignKey("chain.Block", on_delete=models.PROTECT, related_name="validator_rewards")
    amount = amount_field("Reward in smallest units. Must be > 0.")
    reward_type = models.CharField(max_length=16, choices=RewardType.choices)
    status = models.CharField(max_length=16, choices=RewardStatus.choices, default=RewardStatus.PENDING)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["validator", "block", "reward_type"], name="chain_reward_unique_per_block_type"
            ),
            check(Q(amount__gt=0), "chain_reward_amount_positive"),
        ]
        indexes = [models.Index(fields=["validator", "status"])]

    def __str__(self):
        return f"{self.reward_type} {self.amount} -> {self.validator_id}"


class SlashingRecord(BaseModel):
    """Penalty applied to a validator for a defined offence. The same evidence cannot be punished twice."""

    Offence = OffenceType

    validator = models.ForeignKey(Validator, on_delete=models.PROTECT, related_name="slashing_records")
    offence_type = models.CharField(max_length=16, choices=OffenceType.choices)
    slashed_amount = amount_field("Amount removed from the validator's stake. Must be > 0.")
    evidence_hash = models.CharField(
        max_length=64, validators=[hash_validator], help_text="Hash identifying the evidence."
    )
    evidence_description = models.TextField(blank=True)
    block = models.ForeignKey(
        "chain.Block",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="slashing_records",
        help_text="Block in which the slashing was applied.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["validator", "offence_type", "evidence_hash"], name="chain_slash_unique_evidence"
            ),
            check(Q(slashed_amount__gt=0), "chain_slash_amount_positive"),
        ]

    def __str__(self):
        return f"{self.offence_type} {self.slashed_amount} on {self.validator_id}"
