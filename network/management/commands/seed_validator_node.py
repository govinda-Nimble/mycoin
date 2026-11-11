"""
Django management command to seed a Node with nodeType=VALIDATOR and status=ONLINE.

Usage:
    python manage.py seed_validator_node
    python manage.py seed_validator_node --node-id myc-node-001 --endpoint http://localhost:8001 --status ONLINE
    python manage.py seed_validator_node --stake 2000 --commission 7.5
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError

from network.services.node_seeder import NodeSeederError, seed_validator_node


class Command(BaseCommand):
    help = "Seeds a Node with nodeType=VALIDATOR and status=ONLINE linked to an active Validator and Account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--node-id",
            type=str,
            default="myc-val-node-001",
            help="Unique network identity of the node (default: myc-val-node-001)",
        )
        parser.add_argument(
            "--endpoint",
            type=str,
            default="http://localhost:8001",
            help="Communication host/port/URL endpoint (default: http://localhost:8001)",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="validator@mycoin.network",
            help="Email for the validator operator account (default: validator@mycoin.network)",
        )
        parser.add_argument(
            "--stake",
            type=int,
            default=None,
            help="Staked MYC tokens (default: network minValidatorStake)",
        )
        parser.add_argument(
            "--commission",
            type=float,
            default=5.00,
            help="Commission percentage (0-100, default: 5.00)",
        )
        parser.add_argument(
            "--status",
            type=str,
            default="ONLINE",
            help="Node operational status (default: ONLINE)",
        )
        parser.add_argument(
            "--protocol-version",
            type=str,
            default="v1.0.0",
            help="Protocol version string (default: v1.0.0)",
        )
        parser.add_argument(
            "--chain-id",
            type=int,
            default=None,
            help="Specific blockchain network chainId (default: active chain)",
        )

    def handle(self, *args, **options):
        node_id = options["node_id"]
        endpoint = options["endpoint"]
        email = options["email"]
        stake_myc = options["stake"]
        commission = Decimal(str(options["commission"]))
        node_status = options["status"]
        protocol_version = options["protocol_version"]
        chain_id = options["chain_id"]

        self.stdout.write(self.style.NOTICE(f"Seeding Node '{node_id}' with nodeType=VALIDATOR, status={node_status}..."))

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
            raise CommandError(f"Unexpected error while seeding validator node: {err}")

        # Summary output
        node = result.node
        val = result.validator
        acc = result.account
        multiplier = 10 ** node.blockchain.decimals
        stake_tokens = val.totalStake // multiplier

        self.stdout.write(self.style.SUCCESS("\n=================================================="))
        self.stdout.write(self.style.SUCCESS(f" [SUCCESS] {result.message}"))
        self.stdout.write(self.style.SUCCESS("=================================================="))
        self.stdout.write(f" Node ID:          {node.nodeId}")
        self.stdout.write(f" Node Type:        {node.nodeType}")
        self.stdout.write(f" Node Status:      {node.status}")
        self.stdout.write(f" Endpoint:         {node.endpoint}")
        self.stdout.write(f" Protocol Version: {node.protocolVersion}")
        self.stdout.write(f" Blockchain:       {node.blockchain.name} (Chain ID: {node.blockchain.chainId})")
        self.stdout.write(f" P2P Public Key:   {node.p2pPublicKey[:20]}...{node.p2pPublicKey[-10:]}")
        self.stdout.write(f" Validator ID:     {val.id}")
        self.stdout.write(f" Validator Status: {val.status}")
        self.stdout.write(f" Operator Account: {acc.address}")
        self.stdout.write(f" Operator Balance: {acc.balance // multiplier:,} {node.blockchain.symbol} ({acc.balance:,} units)")
        self.stdout.write(f" Total Stake:      {stake_tokens:,} {node.blockchain.symbol} ({val.totalStake:,} units)")
        self.stdout.write(f" Commission:       {val.commissionPercent}%")
        if result.funding_block and result.funding_transaction:
            self.stdout.write(f" Funding Source:   VALIDATOR_RESERVE (0x000...0002)")
            self.stdout.write(f" Funding Block:    #{result.funding_block.height} ({result.funding_block.blockHash[:12]}...)")
            self.stdout.write(f" Funding Tx Hash:  {result.funding_transaction.hash}")
        self.stdout.write(self.style.SUCCESS("==================================================\n"))

