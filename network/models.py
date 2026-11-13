"""Network node and topology models: Node, NodePeer."""
from django.db import models
from django.db.models import F, Q

from common.models import BaseModel, check, hex_validator
from chain.models import (  # noqa: F401
    Blockchain,
    BlockchainStatus,
    Account,
    AccountType,
    SystemAccountType,
    AccountStatus,
)


class NodeType(models.TextChoices):
    VALIDATOR = "VALIDATOR", "Validator node"
    FULL = "FULL", "Full node"
    OBSERVER = "OBSERVER", "Observer node"


class NodeStatus(models.TextChoices):
    ONLINE = "ONLINE", "Online"
    OFFLINE = "OFFLINE", "Offline"
    SYNCING = "SYNCING", "Syncing"
    DISABLED = "DISABLED", "Disabled"


class PeerStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONNECTED = "CONNECTED", "Connected"
    DISCONNECTED = "DISCONNECTED", "Disconnected"
    BANNED = "BANNED", "Banned"


class Node(BaseModel):
    """A network participant. Prepared for future P2P; single-node prototype uses one row."""

    Type = NodeType
    Status = NodeStatus

    blockchain = models.ForeignKey(Blockchain, on_delete=models.PROTECT, related_name="nodes")
    nodeId = models.CharField(
        max_length=128,
        unique=True,
        help_text="Stable network identity of the node (e.g. derived from its P2P public key).",
        error_messages={"unique": "A node with this node ID already exists."},
    )
    nodeType = models.CharField(max_length=16, choices=NodeType.choices, default=NodeType.FULL)
    endpoint = models.CharField(max_length=255, help_text="host:port or URL used to reach the node.")
    status = models.CharField(max_length=16, choices=NodeStatus.choices, default=NodeStatus.OFFLINE)
    lastHeartbeat = models.DateTimeField(null=True, blank=True)
    protocolVersion = models.CharField(max_length=32, blank=True)
    p2pPublicKey = models.CharField(max_length=130, blank=True, validators=[hex_validator])
    validator = models.ForeignKey(
        "staking.Validator",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="nodes",
        help_text="Validator operated by this node (VALIDATOR nodes only).",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blockchain", "endpoint"], name="chain_node_unique_endpoint"),
            check(
                ~Q(nodeType="VALIDATOR") | Q(validator__isnull=False),
                "chain_node_validator_type_needs_validator",
            ),
        ]
        indexes = [
            models.Index(fields=["blockchain", "status"]),
            models.Index(fields=["lastHeartbeat"]),
        ]

    def __str__(self):
        return f"{self.nodeType}:{self.nodeId}"



class NodePeer(BaseModel):
    """Directed connection from a local node to a peer node."""

    Status = PeerStatus

    localNode = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="outbound_peers")
    peerNode = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="inbound_peers")
    status = models.CharField(max_length=16, choices=PeerStatus.choices, default=PeerStatus.PENDING)
    lastConnectedAt = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["localNode", "peerNode"], name="chain_nodepeer_unique_pair"),
            check(~Q(localNode=F("peerNode")), "chain_nodepeer_no_self_peer"),
        ]
        indexes = [models.Index(fields=["localNode", "status"])]

    def __str__(self):
        return f"{self.localNode_id} -> {self.peerNode_id} ({self.status})"
