from django.contrib import admin
from network.models import Blockchain, Node, NodePeer


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


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ("nodeId", "blockchain", "nodeType", "status", "endpoint", "lastHeartbeat")
    search_fields = ("nodeId", "endpoint")
    list_filter = ("status", "nodeType", "blockchain")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-lastHeartbeat",)


@admin.register(NodePeer)
class NodePeerAdmin(admin.ModelAdmin):
    list_display = ("localNode", "peerNode", "status", "lastConnectedAt")
    search_fields = ("localNode__nodeId", "peerNode__nodeId")
    list_filter = ("status",)
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-lastConnectedAt",)
