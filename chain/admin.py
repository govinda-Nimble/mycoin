from django.contrib import admin
from chain.models import Account, Blockchain


@admin.register(Blockchain)
class BlockchainAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "symbol",
        "chainId",
        "decimals",
        "status",
        "blockTimeSeconds",
        "blockReward",
        "latestFinalizedBlock",
    )
    search_fields = ("name", "symbol", "chainId")
    list_filter = ("status", "decimals")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("chainId",)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "address",
        "blockchain",
        "accountType",
        "systemAccountType",
        "balance",
        "nonce",
        "status",
        "creationBlock",
    )
    search_fields = ("address",)
    list_filter = ("accountType", "systemAccountType", "status", "blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-createdAt",)
