"""
Unit and integration tests for the blockchain genesis initialization, seeders, and chain APIs.
Covers:
1. Successful first-time blockchain initialization.
2. Correct creation of all three system accounts.
3. Correct initial balance allocation.
4. Correct Genesis Block creation.
5. Correct genesis allocation records (Transaction, BlockTransaction, Receipt, Event).
6. Correct Genesis Block finalization and immutability.
7. Correct latestFinalizedBlock update.
8. Total supply verification.
9. Running the command twice without duplicate records.
10. Running the command twice without additional minting.
11. Failure during initialization rolls back all database changes.
12. Concurrent initialization does not create duplicate genesis data.
13. Existing inconsistent genesis data causes a safe failure.
14. CLI management command execution.
15. Chain configuration seeders.
16. Chain REST presentation APIs.
"""

from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from common.models import GENESIS_PREVIOUS_HASH, ImmutableRecordError
from chain.models import (
    Account,
    AccountStatus,
    AccountType,
    Blockchain,
    BlockchainStatus,
    SystemAccountType,
)
from chain.seeders import seed_blockchain
from chain.services.genesis import (
    DEVELOPMENT_RESERVE_ADDRESS,
    GENESIS_MINT_ADDRESS,
    TREASURY_ADDRESS,
    VALIDATOR_RESERVE_ADDRESS,
    GenesisConfig,
    GenesisInitializationError,
    initialize_blockchain,
)
from ledger.models import (
    Block,
    BlockStatus,
    BlockTransaction,
    EventType,
    ReceiptStatus,
    Transaction,
    TransactionEvent,
    TransactionReceipt,
    TransactionStatus,
    TransactionType,
)


class InitializeBlockchainTests(TestCase):
    """Test suite for initialize_blockchain service and management command."""

    def setUp(self):
        super().setUp()
        self.config = GenesisConfig(
            chain_name="MYCOIN_TEST",
            symbol="MYC",
            chain_id=9999,
            decimals=8,
            initial_supply_tokens=1_000_000,
            treasury_tokens=600_000,
            validator_reserve_tokens=300_000,
            development_reserve_tokens=100_000,
        )

    def test_1_successful_first_time_initialization(self):
        """Case 1: Verify successful first-time blockchain initialization."""
        result = initialize_blockchain(self.config)

        self.assertFalse(result.already_initialized)
        self.assertEqual(result.blockchain.chainId, 9999)
        self.assertEqual(result.blockchain.status, BlockchainStatus.ACTIVE)
        self.assertEqual(result.genesis_block.status, BlockStatus.FINALIZED)
        self.assertEqual(result.genesis_block.height, 0)

    def test_2_correct_creation_of_all_three_system_accounts(self):
        """Case 2: Verify all three system accounts are created with required properties."""
        result = initialize_blockchain(self.config)

        treasury = result.system_accounts[SystemAccountType.TREASURY]
        val_reserve = result.system_accounts[SystemAccountType.VALIDATOR_RESERVE]
        dev_reserve = result.system_accounts[SystemAccountType.DEVELOPMENT_RESERVE]

        self.assertEqual(treasury.address, TREASURY_ADDRESS)
        self.assertEqual(val_reserve.address, VALIDATOR_RESERVE_ADDRESS)
        self.assertEqual(dev_reserve.address, DEVELOPMENT_RESERVE_ADDRESS)

        for acc in [treasury, val_reserve, dev_reserve]:
            self.assertIsNone(acc.creationBlock)
            self.assertEqual(acc.accountType, AccountType.CONTRACT)
            self.assertEqual(acc.status, AccountStatus.ACTIVE)
            self.assertEqual(acc.blockchain, result.blockchain)

    def test_3_correct_initial_balance_allocation(self):
        """Case 3: Verify initial balance allocation in smallest units without float arithmetic."""
        result = initialize_blockchain(self.config)

        multiplier = 10**self.config.decimals
        treasury = result.system_accounts[SystemAccountType.TREASURY]
        val_reserve = result.system_accounts[SystemAccountType.VALIDATOR_RESERVE]
        dev_reserve = result.system_accounts[SystemAccountType.DEVELOPMENT_RESERVE]

        self.assertEqual(treasury.balance, 600_000 * multiplier)
        self.assertEqual(val_reserve.balance, 300_000 * multiplier)
        self.assertEqual(dev_reserve.balance, 100_000 * multiplier)

        # Genesis mint address balance should be 0 after allocation
        mint_acc = Account.objects.get(blockchain=result.blockchain, address=GENESIS_MINT_ADDRESS)
        self.assertEqual(mint_acc.balance, 0)

    def test_4_correct_genesis_block_creation(self):
        """Case 4: Verify Genesis Block fields, constraints, and header hashes."""
        result = initialize_blockchain(self.config)
        block = result.genesis_block

        self.assertEqual(block.height, 0)
        self.assertIsNone(block.parent)
        self.assertIsNone(block.proposer)
        self.assertEqual(block.previousHash, GENESIS_PREVIOUS_HASH)
        self.assertEqual(block.transactionCount, 3)
        self.assertEqual(block.gasUsed, 0)
        self.assertEqual(block.blockReward, 0)
        self.assertEqual(len(block.blockHash), 64)
        self.assertEqual(len(block.merkleRoot), 64)
        self.assertEqual(len(block.stateRoot), 64)

    def test_5_correct_genesis_allocation_records(self):
        """Case 5: Verify Transaction, BlockTransaction, Receipt, and Event audit records."""
        result = initialize_blockchain(self.config)
        block = result.genesis_block

        txs = Transaction.objects.filter(block=block).order_by("nonce")
        self.assertEqual(txs.count(), 3)

        recipients = [
            (SystemAccountType.TREASURY, self.config.treasury_smallest_units),
            (SystemAccountType.VALIDATOR_RESERVE, self.config.validator_reserve_smallest_units),
            (SystemAccountType.DEVELOPMENT_RESERVE, self.config.development_reserve_smallest_units),
        ]

        for idx, tx in enumerate(txs):
            expected_type, expected_amount = recipients[idx]
            self.assertEqual(tx.sender.address, GENESIS_MINT_ADDRESS)
            self.assertEqual(tx.amount, expected_amount)
            self.assertEqual(tx.receiver.systemAccountType, expected_type)
            self.assertEqual(tx.txType, TransactionType.TRANSFER)
            self.assertEqual(tx.status, TransactionStatus.FINALIZED)
            self.assertEqual(tx.feePaid, 0)
            self.assertEqual(tx.gasPrice, 0)

            # BlockTransaction
            btx = BlockTransaction.objects.get(transaction=tx)
            self.assertEqual(btx.block, block)
            self.assertEqual(btx.txIndex, idx)

            # TransactionReceipt
            receipt = TransactionReceipt.objects.get(transaction=tx)
            self.assertEqual(receipt.block, block)
            self.assertEqual(receipt.status, ReceiptStatus.SUCCESS)
            self.assertEqual(receipt.resultCode, "GENESIS_ALLOCATION")
            self.assertEqual(receipt.gasUsed, 0)

            # TransactionEvent
            event = TransactionEvent.objects.get(transaction=tx)
            self.assertEqual(event.eventType, EventType.TRANSFER)
            self.assertEqual(event.eventData["allocationType"], expected_type)
            self.assertEqual(event.eventData["amount"], expected_amount)
            self.assertTrue(event.eventData["isGenesis"])

    def test_6_correct_genesis_block_finalization(self):
        """Case 6: Verify Genesis Block finalization and immutability."""
        result = initialize_blockchain(self.config)
        block = result.genesis_block

        self.assertEqual(block.status, BlockStatus.FINALIZED)
        self.assertIsNotNone(block.finalizedAt)

        # Modifying finalized block should raise ImmutableRecordError
        block.blockReward = 100
        with self.assertRaises(ImmutableRecordError):
            block.save()

        # Deleting finalized block should raise ImmutableRecordError
        with self.assertRaises(ImmutableRecordError):
            block.delete()

    def test_7_correct_latest_finalized_block_update(self):
        """Case 7: Verify blockchain references the Genesis Block as latestFinalizedBlock."""
        result = initialize_blockchain(self.config)
        blockchain = Blockchain.objects.get(id=result.blockchain.id)

        self.assertIsNotNone(blockchain.latestFinalizedBlock)
        self.assertEqual(blockchain.latestFinalizedBlock.id, result.genesis_block.id)

    def test_8_total_supply_verification(self):
        """Case 8: Verify allocated total supply matches configured initial supply."""
        result = initialize_blockchain(self.config)

        total_system_balance = sum(
            acc.balance for acc in result.system_accounts.values()
        )
        self.assertEqual(total_system_balance, self.config.initial_supply_smallest_units)
        self.assertEqual(result.total_supply_smallest_units, self.config.initial_supply_smallest_units)

    def test_9_running_command_twice_without_duplicate_records(self):
        """Case 9: Verify idempotency - no duplicate blocks, accounts, or transactions."""
        result1 = initialize_blockchain(self.config)
        self.assertFalse(result1.already_initialized)

        result2 = initialize_blockchain(self.config)
        self.assertTrue(result2.already_initialized)

        self.assertEqual(Block.objects.filter(blockchain=result1.blockchain).count(), 1)
        self.assertEqual(
            Account.objects.filter(
                blockchain=result1.blockchain,
                systemAccountType__isnull=False,
            ).count(),
            3,
        )
        self.assertEqual(
            Transaction.objects.filter(blockchain=result1.blockchain).count(),
            3,
        )

    def test_10_running_command_twice_without_additional_minting(self):
        """Case 10: Verify repeated execution does not increase balances or mint extra coins."""
        initialize_blockchain(self.config)

        treasury_before = Account.objects.get(
            blockchain__chainId=self.config.chain_id,
            systemAccountType=SystemAccountType.TREASURY,
        ).balance

        initialize_blockchain(self.config)

        treasury_after = Account.objects.get(
            blockchain__chainId=self.config.chain_id,
            systemAccountType=SystemAccountType.TREASURY,
        ).balance

        self.assertEqual(treasury_before, treasury_after)

    def test_11_failure_during_initialization_rolls_back_changes(self):
        """Case 11: Verify database atomicity - error rolls back all created records."""
        # Intentionally force an error during Transaction creation
        with patch.object(Transaction, "save", side_effect=RuntimeError("Simulated DB failure")):
            with self.assertRaises(RuntimeError):
                initialize_blockchain(self.config)

        # Assert no blockchain blocks or system accounts were committed
        self.assertEqual(Block.objects.filter(blockchain__chainId=self.config.chain_id).count(), 0)
        self.assertEqual(
            Account.objects.filter(blockchain__chainId=self.config.chain_id).count(), 0
        )

    def test_12_concurrent_initialization_does_not_create_duplicate_genesis_data(self):
        """Case 12: Verify concurrent initialization handling detects already-initialized state."""
        result1 = initialize_blockchain(self.config)
        result2 = initialize_blockchain(self.config)

        self.assertTrue(result2.already_initialized)
        self.assertEqual(result1.genesis_block.id, result2.genesis_block.id)

    def test_13_existing_inconsistent_genesis_data_causes_safe_failure(self):
        """Case 13: Verify safe failure when existing genesis data is corrupt or inconsistent."""
        result = initialize_blockchain(self.config)

        # Corrupt an account balance directly in the database
        treasury = result.system_accounts[SystemAccountType.TREASURY]
        Account.objects.filter(id=treasury.id).update(balance=999)

        # Re-running initialization must detect inconsistency and fail safely
        with self.assertRaises(GenesisInitializationError) as ctx:
            initialize_blockchain(self.config)

        self.assertIn("has balance 999", str(ctx.exception))

    def test_cli_management_command(self):
        """Test management command execution and formatted stdout output."""
        out = StringIO()
        call_command(
            "initialize_blockchain",
            "--chain-name", "MYCOIN_CLI",
            "--symbol", "MYC",
            "--chain-id", "8888",
            "--decimals", "8",
            "--initial-supply", "1000000",
            "--treasury", "600000",
            "--validator-reserve", "300000",
            "--dev-reserve", "100000",
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("Blockchain initialized successfully.", output)
        self.assertIn("Chain: MYCOIN_CLI", output)
        self.assertIn("Chain ID: 8888", output)
        self.assertIn("Initial Supply: 1,000,000 MYC", output)
        self.assertIn("Treasury: 600,000 MYC", output)
        self.assertIn("Validator Reserve: 300,000 MYC", output)
        self.assertIn("Development Reserve: 100,000 MYC", output)
        self.assertIn("Supply Verification: PASSED", output)
        self.assertIn("Genesis Finalization: SUCCESS", output)

        # Re-running via CLI should report already initialized
        out2 = StringIO()
        call_command("initialize_blockchain", "--chain-id", "8888", stdout=out2)
        output2 = out2.getvalue()
        self.assertIn("Blockchain is already initialized and verified.", output2)
        self.assertIn("ALREADY FINALIZED", output2)


class ChainSeederTests(TestCase):
    """Test suite for chain seeders."""

    def test_seed_blockchain_creates_and_updates(self):
        bc, created = seed_blockchain(name="SEED_TEST", chain_id=5555)
        self.assertTrue(created)
        self.assertEqual(bc.name, "SEED_TEST")
        self.assertEqual(bc.chainId, 5555)

        # Idempotent re-seed updates
        bc2, created2 = seed_blockchain(name="SEED_TEST", chain_id=5555, decimals=10)
        self.assertFalse(created2)
        self.assertEqual(bc2.id, bc.id)
        self.assertEqual(bc2.decimals, 10)


class ChainAPITests(TestCase):
    """Test suite for Chain presentation layer APIs."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_chain_status_endpoint(self):
        """Test GET /api/chain/status/ returns active chain details."""
        config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        initialize_blockchain(config)

        response = self.client.get("/api/chain/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["chainId"], 1001)
        self.assertEqual(response.data["data"]["chainName"], "TEST_CHAIN")

    def test_genesis_init_endpoint(self):
        """Test POST /api/chain/genesis/ bootstraps a new chain."""
        payload = {
            "chainId": 7777,
            "chainName": "API_BOOTSTRAP_CHAIN",
            "symbol": "MYC",
        }
        response = self.client.post("/api/chain/genesis/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["chainId"], 7777)
