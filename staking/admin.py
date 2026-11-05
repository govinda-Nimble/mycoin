from django.contrib import admin
from staking.models import (
    BlockVote,
    RewardStatus,
    SlashingRecord,
    Stake,
    Validator,
    ValidatorReward,
)


@admin.register(Validator)
class ValidatorAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "status",
        "totalStake",
        "commissionPercent",
        "activatedAt",
        "lastProposedBlock",
        "lastActiveAt",
    )
    search_fields = ("account__address", "publicKey")
    list_filter = ("status", "account__blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-totalStake",)


@admin.register(Stake)
class StakeAdmin(admin.ModelAdmin):
    list_display = (
        "validator",
        "stakerAccount",
        "amount",
        "status",
        "stakedAtHeight",
        "lockPeriodBlocks",
        "unlockHeight",
        "stakedAt",
    )
    search_fields = ("validator__account__address", "stakerAccount__address")
    list_filter = ("status", "validator__account__blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-stakedAt",)


@admin.register(BlockVote)
class BlockVoteAdmin(admin.ModelAdmin):
    list_display = ("block", "validator", "voteType", "votingPower", "votedAt")
    search_fields = ("block__blockHash", "validator__account__address")
    list_filter = ("voteType", "block__blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-votedAt",)


@admin.register(ValidatorReward)
class ValidatorRewardAdmin(admin.ModelAdmin):
    list_display = ("validator", "block", "rewardType", "amount", "status", "createdAt")
    search_fields = ("validator__account__address", "block__blockHash")
    list_filter = ("rewardType", "status", "block__blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-createdAt",)


@admin.register(SlashingRecord)
class SlashingRecordAdmin(admin.ModelAdmin):
    list_display = ("validator", "offenceType", "slashedAmount", "block", "createdAt")
    search_fields = ("validator__account__address", "evidenceHash", "evidenceDescription")
    list_filter = ("offenceType", "block__blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-createdAt",)
