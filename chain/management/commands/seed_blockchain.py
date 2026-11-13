"""
Django management command to seed the primary Blockchain record.

Usage:
    python manage.py seed_blockchain
    python manage.py seed_blockchain --name MYCOIN --symbol MYC --decimals 8 --chain-id 1001
"""

from django.core.management.base import BaseCommand
from chain.models import BlockchainStatus
from chain.seeders import seed_blockchain


class Command(BaseCommand):
    help = "Seeds the initial Blockchain configuration record (name=MYCOIN, symbol=MYC, decimals=8)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
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
            "--decimals",
            type=int,
            default=8,
            help="Smallest unit decimals (default: 8)",
        )
        parser.add_argument(
            "--chain-id",
            type=int,
            default=1001,
            help="Unique network chain ID (default: 1001)",
        )
        parser.add_argument(
            "--status",
            type=str,
            default=BlockchainStatus.ACTIVE,
            choices=[c[0] for c in BlockchainStatus.choices],
            help="Blockchain status: INITIALIZING, ACTIVE, or HALTED (default: ACTIVE)",
        )
        parser.add_argument(
            "--block-time",
            type=int,
            default=5,
            help="Target block time in seconds (default: 5)",
        )
        parser.add_argument(
            "--block-reward",
            type=int,
            default=None,
            help="Block reward in smallest units (default: 5 * 10^decimals)",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding blockchain configuration..."))

        name = options["name"]
        symbol = options["symbol"]
        decimals = options["decimals"]
        chain_id = options["chain_id"]
        status = options["status"]
        block_time = options["block_time"]
        block_reward = options["block_reward"]

        try:
            blockchain, created = seed_blockchain(
                name=name,
                symbol=symbol,
                decimals=decimals,
                chain_id=chain_id,
                status=status,
                block_time_seconds=block_time,
                block_reward=block_reward,
            )

            action = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] Successfully {action} Blockchain record:\n"
                    f"   - ID: {blockchain.id}\n"
                    f"   - Name: {blockchain.name}\n"
                    f"   - Symbol: {blockchain.symbol}\n"
                    f"   - Decimals: {blockchain.decimals}\n"
                    f"   - Chain ID: {blockchain.chainId}\n"
                    f"   - Status: {blockchain.status}\n"
                    f"   - Block Time: {blockchain.blockTimeSeconds}s\n"
                    f"   - Block Reward: {blockchain.blockReward} units\n"
                    f"   - Max Block Gas: {blockchain.maxBlockGas:,}\n"
                    f"   - Min Validator Stake: {blockchain.minValidatorStake:,} units"
                )
            )
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"[ERROR] Failed to seed blockchain: {exc}"))
            raise

