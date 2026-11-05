"""Blockchain and network models: Blockchain, Node, NodePeer."""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from common.models import BaseModel, amount_field, check, hex_validator


class BlockchainStatus(models.TextChoices):
    INITIALIZING = "INITIALIZING", "Initializing"
    ACTIVE = "ACTIVE", "Active"
    HALTED = "HALTED", "Halted"


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
