"""
Django management command to initialize the blockchain with its genesis block and initial supply.

Usage:
    python manage.py initialize_blockchain
    python manage.py initialize_blockchain --chain-id 1001 --initial-supply 1000000 --treasury 600000 --validator-reserve 300000 --dev-reserve 100000
"""

from django.core.management.base import BaseCommand, CommandError
from network.services.genesis import (
    GenesisConfig,
    GenesisInitializationError,
    initialize_blockchain,
)
from wallets.models import SystemAccountType


class Command(BaseCommand):
    help = "Initializes the account-based blockchain with its Genesis Block and initial coin supply distribution."

    def add_arguments(self, parser):
        parser.add_argument(
            "--chain-name",
            type=str,
            default="MYCOIN",
            help="Name of the blockchain (default: MYCOIN)",
        )
        parser.add_argument(
            "--symbol",
            type=str,
            default="MYC",
            help="Native currency symbol (default: MYC)",
        )
        parser.add_argument(
            "--chain-id",
            type=int,
            default=1001,
            help="Network chain ID (default: 1001)",
        )
        parser.add_argument(
            "--decimals",
            type=int,
            default=8,
            help="Decimal precision (default: 8)",
        )
        parser.add_argument(
            "--initial-supply",
            type=int,
            default=1_000_000,
            help="Initial coin supply in whole tokens (default: 1,000,000)",
        )
        parser.add_argument(
            "--treasury",
            type=int,
            default=600_000,
            help="Treasury allocation in whole tokens (default: 600,000)",
        )
        parser.add_argument(
            "--validator-reserve",
            type=int,
            default=300_000,
            help="Validator reserve allocation in whole tokens (default: 300,000)",
        )
        parser.add_argument(
            "--dev-reserve",
            type=int,
            default=100_000,
            help="Development reserve allocation in whole tokens (default: 100,000)",
        )

    def handle(self, *args, **options):
        config = GenesisConfig(
            chain_name=options["chain_name"],
            symbol=options["symbol"],
            chain_id=options["chain_id"],
            decimals=options["decimals"],
            initial_supply_tokens=options["initial_supply"],
            treasury_tokens=options["treasury"],
            validator_reserve_tokens=options["validator_reserve"],
            development_reserve_tokens=options["dev_reserve"],
        )

        try:
            config.validate()
        except ValueError as err:
            raise CommandError(f"Configuration error: {err}")

        try:
            result = initialize_blockchain(config)
        except GenesisInitializationError as err:
            raise CommandError(f"Genesis initialization error: {err}")
        except Exception as err:
            raise CommandError(f"Unexpected initialization failure: {err}")

        # Format output
        symbol = config.symbol
        multiplier = config.multiplier

        treasury_acc = result.system_accounts[SystemAccountType.TREASURY]
        val_acc = result.system_accounts[SystemAccountType.VALIDATOR_RESERVE]
        dev_acc = result.system_accounts[SystemAccountType.DEVELOPMENT_RESERVE]

        treasury_tokens = treasury_acc.balance // multiplier
        val_tokens = val_acc.balance // multiplier
        dev_tokens = dev_acc.balance // multiplier
        total_tokens = result.total_supply_smallest_units // multiplier

        if result.already_initialized:
            header = self.style.WARNING("Blockchain is already initialized and verified.\n")
            finalization_status = self.style.SUCCESS("ALREADY FINALIZED")
        else:
            header = self.style.SUCCESS("Blockchain initialized successfully.\n")
            finalization_status = self.style.SUCCESS("SUCCESS")

        output = [
            header,
            f"Chain: {result.blockchain.name}",
            f"Chain ID: {result.blockchain.chainId}",
            f"Genesis Block: {result.genesis_block.height}",
            f"Initial Supply: {total_tokens:,} {symbol}",
            "",
            "System Accounts:",
            f"- Treasury: {treasury_tokens:,} {symbol} ({treasury_acc.address})",
            f"- Validator Reserve: {val_tokens:,} {symbol} ({val_acc.address})",
            f"- Development Reserve: {dev_tokens:,} {symbol} ({dev_acc.address})",
            "",
            f"Supply Verification: {self.style.SUCCESS('PASSED')}",
            f"Genesis Finalization: {finalization_status}",
        ]

        self.stdout.write("\n".join(output))

