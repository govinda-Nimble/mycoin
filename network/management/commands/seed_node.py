"""
Django management command to seed a Node (defaults to nodeType=VALIDATOR and status=ONLINE).

Usage:
    python manage.py seed_node
    python manage.py seed_node --node-type VALIDATOR --status ONLINE --node-id myc-val-node-001
    python manage.py seed_node --node-type FULL --status ONLINE --node-id myc-full-node-002 --endpoint http://localhost:8002
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from network.models import Blockchain, BlockchainStatus, Node, NodeStatus, NodeType
from network.services.node_seeder import NodeSeederError, seed_validator_node
from wallets.services.wallet_service import generate_keypair


class Command(BaseCommand):
    help = "Seeds a blockchain Node. Defaults to nodeType=VALIDATOR and status=ONLINE."

    def add_arguments(self, parser):
        parser.add_argument(
            "--node-type",
            type=str,
            default="VALIDATOR",
            choices=["VALIDATOR", "FULL", "OBSERVER", "validator", "full", "observer"],
            help="Node type: VALIDATOR, FULL, or OBSERVER (default: VALIDATOR)",
        )
        parser.add_argument(
            "--status",
            type=str,
            default="ONLINE",
            choices=["ONLINE", "OFFLINE", "SYNCING", "DISABLED", "online", "offline", "syncing", "disabled"],
            help="Node operational status (default: ONLINE)",
        )
        parser.add_argument(
            "--node-id",
            type=str,
            default=None,
            help="Unique node identifier (default: myc-val-node-001 or myc-full-node-001)",
        )
        parser.add_argument(
            "--endpoint",
            type=str,
            default=None,
            help="Node HTTP/RPC endpoint (default: http://localhost:8001)",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="validator@mycoin.network",
            help="Validator operator email (VALIDATOR nodeType only)",
        )
        parser.add_argument(
            "--stake",
            type=int,
            default=None,
            help="Stake in whole MYC tokens (VALIDATOR nodeType only)",
        )
        parser.add_argument(
            "--commission",
            type=float,
            default=5.00,
            help="Commission percent (VALIDATOR nodeType only)",
        )
        parser.add_argument(
            "--protocol-version",
            type=str,
            default="v1.0.0",
            help="Protocol version (default: v1.0.0)",
        )
        parser.add_argument(
            "--chain-id",
            type=int,
            default=None,
            help="Blockchain chain ID",
        )

    def handle(self, *args, **options):
        node_type = options["node_type"].strip().upper()
        node_status = options["status"].strip().upper()
        protocol_version = options["protocol_version"]
        chain_id = options["chain_id"]

        # Default identifiers based on nodeType
        if node_type == "VALIDATOR":
            node_id = options["node_id"] or "myc-val-node-001"
            endpoint = options["endpoint"] or "http://localhost:8001"
            email = options["email"]
            stake_myc = options["stake"]
            commission = Decimal(str(options["commission"]))

            self.stdout.write(self.style.NOTICE(f"Seeding VALIDATOR Node '{node_id}' with status {node_status}..."))
            try:
                result = seed_validator_node(
                    node_id=node_id,
                    endpoint=endpoint,
                    operator_email=email,
                    stake_amount_myc=stake_myc,
                    commission_percent=commission,
                    protocol_version=protocol_version,
                    node_status=node_status,
                    chain_id=chain_id,
                )
            except NodeSeederError as err:
                raise CommandError(str(err))
            except Exception as err:
                raise CommandError(f"Seeding error: {err}")

            node = result.node
            val = result.validator
            self.stdout.write(self.style.SUCCESS(f"\n[SUCCESS] {result.message}"))
            self.stdout.write(f" Node ID:     {node.nodeId}")
            self.stdout.write(f" Node Type:   {node.nodeType}")
            self.stdout.write(f" Node Status: {node.status}")
            self.stdout.write(f" Endpoint:    {node.endpoint}")
            self.stdout.write(f" Validator:   {val.id} (Stake: {val.totalStake:,} units)")
            self.stdout.write(f" Account:     {result.account.address}")
            return

        # FULL or OBSERVER Node (non-validator)
        node_id = options["node_id"] or "myc-full-node-001"
        endpoint = options["endpoint"] or "http://localhost:8002"

        self.stdout.write(self.style.NOTICE(f"Seeding {node_type} Node '{node_id}' with status {node_status}..."))

        with transaction.atomic():
            if chain_id is not None:
                blockchain = Blockchain.objects.select_for_update().filter(chainId=chain_id).first()
            else:
                blockchain = Blockchain.objects.select_for_update().filter(status=BlockchainStatus.ACTIVE).first()

            if not blockchain:
                raise CommandError("No active blockchain found. Run 'python manage.py initialize_blockchain' first.")

            _, pubkey, _ = generate_keypair()
            now = timezone.now()

            node = Node.objects.filter(nodeId=node_id).first()
            if not node:
                node = Node.objects.filter(blockchain=blockchain, endpoint=endpoint).first()

            if node:
                node.nodeId = node_id
                node.nodeType = node_type
                node.endpoint = endpoint
                node.status = node_status
                node.validator = None
                node.p2pPublicKey = pubkey
                node.protocolVersion = protocol_version
                node.lastHeartbeat = now
                node.full_clean()
                node.save()
                action = "Updated"
            else:
                node = Node.objects.create(
                    blockchain=blockchain,
                    nodeId=node_id,
                    nodeType=node_type,
                    endpoint=endpoint,
                    status=node_status,
                    lastHeartbeat=now,
                    protocolVersion=protocol_version,
                    p2pPublicKey=pubkey,
                    validator=None,
                )
                node.full_clean()
                action = "Created"

        self.stdout.write(self.style.SUCCESS(f"\n[SUCCESS] {action} {node.nodeType} Node '{node.nodeId}' with status {node.status}."))
        self.stdout.write(f" Node ID:     {node.nodeId}")
        self.stdout.write(f" Node Type:   {node.nodeType}")
        self.stdout.write(f" Node Status: {node.status}")
        self.stdout.write(f" Endpoint:    {node.endpoint}")

