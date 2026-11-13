from django.contrib import admin
from wallets.models import Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("address", "user", "name", "walletType", "status", "createdAt")
    search_fields = ("address", "user__email", "name", "publicKey")
    list_filter = ("walletType", "status", "createdAt")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-createdAt",)
