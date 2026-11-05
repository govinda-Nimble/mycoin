from django.contrib import admin
from ledger.models import (
    Block,
    BlockTransaction,
    MempoolTransaction,
    Transaction,
    TransactionEvent,
    TransactionReceipt,
)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = (
        "height",
        "blockHash_short",
        "blockchain",
        "status",
        "transactionCount",
        "gasUsed",
        "blockReward",
        "proposer",
        "timestamp",
        "finalizedAt",
    )
    search_fields = ("blockHash", "previousHash", "height")
    list_filter = ("status", "blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt", "finalizedAt")
    ordering = ("-height",)

    @admin.display(description="Block Hash")
    def blockHash_short(self, obj):
        return f"{obj.blockHash[:10]}...{obj.blockHash[-6:]}" if obj.blockHash else "-"


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "hash_short",
        "blockchain",
        "txType",
        "sender",
        "receiverAddress_short",
        "amount",
        "nonce",
        "status",
        "block",
        "createdAt",
    )
    search_fields = ("hash", "sender__address", "receiverAddress")
    list_filter = ("status", "txType", "blockchain")
    readonly_fields = ("id", "hash", "createdAt", "updatedAt")
    ordering = ("-createdAt",)

    @admin.display(description="Tx Hash")
    def hash_short(self, obj):
        return f"{obj.hash[:10]}...{obj.hash[-6:]}" if obj.hash else "-"

    @admin.display(description="Receiver Address")
    def receiverAddress_short(self, obj):
        return f"{obj.receiverAddress[:8]}...{obj.receiverAddress[-6:]}" if obj.receiverAddress else "-"


@admin.register(BlockTransaction)
class BlockTransactionAdmin(admin.ModelAdmin):
    list_display = ("block", "txIndex", "transaction", "createdAt")
    search_fields = ("block__blockHash", "transaction__hash")
    list_filter = ("block__blockchain",)
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("block", "txIndex")


@admin.register(TransactionReceipt)
class TransactionReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "transaction",
        "block",
        "status",
        "gasUsed",
        "effectiveGasPrice",
        "resultCode",
        "createdAt",
    )
    search_fields = ("transaction__hash", "resultCode", "resultMessage")
    list_filter = ("status", "block__blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-createdAt",)


@admin.register(TransactionEvent)
class TransactionEventAdmin(admin.ModelAdmin):
    list_display = ("transaction", "eventType", "eventIndex", "createdAt")
    search_fields = ("transaction__hash", "eventType")
    list_filter = ("eventType",)
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("transaction", "eventIndex")


@admin.register(MempoolTransaction)
class MempoolTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction", "node", "priority", "status", "arrivalTime", "expiresAt")
    search_fields = ("transaction__hash", "node__nodeId")
    list_filter = ("status", "node__blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-priority", "arrivalTime")
