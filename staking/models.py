"""Proof-of-Stake models: Validator, Stake, BlockVote, ValidatorReward, SlashingRecord.

Proposer selection, vote counting, reward calculation and slashing execution are NOT here: they are domain
services added in a later phase. These models only store their inputs and results.
"""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from common.models import BaseModel, amount_field, check, hash_validator, hex_validator


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

    account = models.OneToOneField("wallets.Account", on_delete=models.PROTECT, related_name="validator")
    publicKey = models.CharField(
        max_length=130,
        unique=True,
        validators=[hex_validator],
        help_text="Key used to verify this validator's proposals and votes.",
        error_messages={"unique": "A validator with this public key already exists."},
    )
    status = models.CharField(max_length=16, choices=ValidatorStatus.choices, default=ValidatorStatus.PENDING)
    totalStake = amount_field(
        "Denormalized sum of active stakes. Updated in the same atomic block as the Stake rows.", default=0
    )
    commissionPercent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Share of rewards kept by the validator (0-100).",
    )
    activatedAt = models.DateTimeField(null=True, blank=True)
    lastProposedBlock = models.ForeignKey(
        "ledger.Block",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="last_proposed_by",
    )
    lastActiveAt = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            check(Q(totalStake__gte=0), "chain_validator_stake_non_negative"),
            check(
                Q(commissionPercent__gte=0, commissionPercent__lte=100),
                "chain_validator_commission_range",
            ),
            check(~Q(status="ACTIVE") | Q(activatedAt__isnull=False), "chain_validator_active_has_time"),
        ]
        indexes = [models.Index(fields=["status", "-totalStake"])]

    def __str__(self):
        return f"Validator {self.account_id} ({self.status})"

    def clean(self):
        super().clean()
        if self.account_id and self.account.accountType != "EOA":
            raise ValidationError({"account": "Only externally owned accounts can be validators."})


class Stake(BaseModel):
    """One staking action by an account towards a validator (one row per STAKE transaction).

    Lock rules are in blocks, not wall-clock time, so they are deterministic:
    * ``lockPeriodBlocks``: minimum blocks the stake stays staked before unstaking is allowed.
    * ``unlockHeight``: set when unstaking starts; funds are withdrawable from this height on.
    """

    Status = StakeStatus

    validator = models.ForeignKey(Validator, on_delete=models.PROTECT, related_name="stakes")
    stakerAccount = models.ForeignKey("wallets.Account", on_delete=models.PROTECT, related_name="stakes")
    amount = amount_field("Staked amount in smallest units. Must be > 0.")
    status = models.CharField(max_length=16, choices=StakeStatus.choices, default=StakeStatus.ACTIVE)
    stakedAtHeight = models.PositiveBigIntegerField(help_text="Finalized height at which the stake started.")
    stakedAt = models.DateTimeField(default=timezone.now)
    lockPeriodBlocks = models.PositiveIntegerField(default=0)
    unlockHeight = models.PositiveBigIntegerField(null=True, blank=True)
    unstakeRequestedAt = models.DateTimeField(null=True, blank=True)
    stakeTransaction = models.OneToOneField(
        "ledger.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stake_record",
        help_text="STAKE transaction. Null for genesis stakes.",
    )
    unstakeTransaction = models.OneToOneField(
        "ledger.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="unstake_record",
    )

    class Meta:
        constraints = [
            check(Q(amount__gt=0), "chain_stake_amount_positive"),
            check(
                Q(status="ACTIVE") | Q(unlockHeight__isnull=False, unstakeRequestedAt__isnull=False),
                "chain_stake_unbonding_needs_unlock",
            ),
            check(
                Q(unlockHeight__isnull=True) | Q(unlockHeight__gte=F("stakedAtHeight")),
                "chain_stake_unlock_after_stake",
            ),
        ]
        indexes = [
            models.Index(fields=["validator", "status"]),
            models.Index(fields=["stakerAccount", "status"]),
        ]

    def __str__(self):
        return f"Stake {self.amount} -> {self.validator_id} ({self.status})"

    def clean(self):
        super().clean()
        if (
            self.validator_id
            and self.stakerAccount_id
            and self.validator.account.blockchain_id != self.stakerAccount.blockchain_id
        ):
            raise ValidationError("Validator and staker account belong to different blockchains.")


class BlockVote(BaseModel):
    """A validator's vote on a proposed block. Voting power is a snapshot taken at vote time."""

    Type = VoteType

    block = models.ForeignKey("ledger.Block", on_delete=models.PROTECT, related_name="votes")
    validator = models.ForeignKey(Validator, on_delete=models.PROTECT, related_name="votes")
    voteType = models.CharField(max_length=16, choices=VoteType.choices)
    votingPower = amount_field("Validator's voting power (stake) at vote time. Must be > 0.")
    signature = models.CharField(max_length=200, validators=[hex_validator])
    votedAt = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["block", "validator"], name="chain_vote_one_per_validator"),
            check(Q(votingPower__gt=0), "chain_vote_power_positive"),
        ]
        indexes = [models.Index(fields=["block", "voteType"])]

    def __str__(self):
        return f"{self.voteType} by {self.validator_id} on {self.block_id}"

    def clean(self):
        super().clean()
        if self.block_id and self.validator_id and self.block.blockchain_id != self.validator.account.blockchain_id:
            raise ValidationError("Block and validator belong to different blockchains.")


class ValidatorReward(BaseModel):
    """Reward earned by a validator for a block. Paid (credited to the account) at finalization."""

    Type = RewardType
    Status = RewardStatus

    validator = models.ForeignKey(Validator, on_delete=models.PROTECT, related_name="rewards")
    block = models.ForeignKey("ledger.Block", on_delete=models.PROTECT, related_name="validator_rewards")
    amount = amount_field("Reward in smallest units. Must be > 0.")
    rewardType = models.CharField(max_length=16, choices=RewardType.choices)
    status = models.CharField(max_length=16, choices=RewardStatus.choices, default=RewardStatus.PENDING)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["validator", "block", "rewardType"], name="chain_reward_unique_per_block_type"
            ),
            check(Q(amount__gt=0), "chain_reward_amount_positive"),
        ]
        indexes = [models.Index(fields=["validator", "status"])]

    def __str__(self):
        return f"{self.rewardType} {self.amount} -> {self.validator_id}"


class SlashingRecord(BaseModel):
    """Penalty applied to a validator for a defined offence. The same evidence cannot be punished twice."""

    Offence = OffenceType

    validator = models.ForeignKey(Validator, on_delete=models.PROTECT, related_name="slashing_records")
    offenceType = models.CharField(max_length=16, choices=OffenceType.choices)
    slashedAmount = amount_field("Amount removed from the validator's stake. Must be > 0.")
    evidenceHash = models.CharField(
        max_length=64, validators=[hash_validator], help_text="Hash identifying the evidence."
    )
    evidenceDescription = models.TextField(blank=True)
    block = models.ForeignKey(
        "ledger.Block",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="slashing_records",
        help_text="Block in which the slashing was applied.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["validator", "offenceType", "evidenceHash"], name="chain_slash_unique_evidence"
            ),
            check(Q(slashedAmount__gt=0), "chain_slash_amount_positive"),
        ]

    def __str__(self):
        return f"{self.offenceType} {self.slashedAmount} on {self.validator_id}"
