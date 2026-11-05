from django.contrib import admin
from wallets.models import Account, Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("address", "user", "name", "walletType", "status", "createdAt")
    search_fields = ("address", "user__email", "name", "publicKey")
    list_filter = ("walletType", "status", "createdAt")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-createdAt",)


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
        "wallet",
        "creationBlock",
    )
    search_fields = ("address", "wallet__address", "wallet__user__email")
    list_filter = ("accountType", "systemAccountType", "status", "blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-createdAt",)
