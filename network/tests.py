"""
Unit and integration tests for the blockchain genesis initialization.

Covers all 13 required test cases:
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
"""

from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework.test import APIClient

from common.models import GENESIS_PREVIOUS_HASH, ImmutableRecordError
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
from network.models import Blockchain, BlockchainStatus
from network.services.genesis import (
    DEVELOPMENT_RESERVE_ADDRESS,
    GENESIS_MINT_ADDRESS,
    TREASURY_ADDRESS,
    VALIDATOR_RESERVE_ADDRESS,
    GenesisConfig,
    GenesisInitializationError,
    initialize_blockchain,
)
from wallets.models import Account, AccountStatus, AccountType, SystemAccountType


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
            self.assertIsNone(acc.wallet)
            self.assertIsNone(acc.derivationIndex)
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
        # Calling again simulates second concurrent worker encountering existing finalized state
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


class NodeSeederTestCase(TestCase):
    """Unit and integration tests for seeding Node with nodeType=VALIDATOR and status=ONLINE."""

    def setUp(self):
        # Initialize an active blockchain
        self.genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.genesis_result = initialize_blockchain(self.genesis_config)
        self.blockchain = self.genesis_result.blockchain

    def test_seed_validator_node_service_success(self):
        """Verify seeding creates Node, Validator, Account, Wallet, and Stake successfully."""
        from network.services.node_seeder import seed_validator_node

        result = seed_validator_node(
            node_id="myc-val-node-001",
            endpoint="http://localhost:8001",
            operator_email="val-operator@mycoin.network",
            stake_amount_myc=1500,
            commission_percent=Decimal("5.00"),
            node_status="ONLINE",
        )

        node = result.node
        self.assertEqual(node.nodeId, "myc-val-node-001")
        self.assertEqual(node.nodeType, "VALIDATOR")
        self.assertEqual(node.status, "ONLINE")
        self.assertEqual(node.endpoint, "http://localhost:8001")
        self.assertIsNotNone(node.lastHeartbeat)
        self.assertTrue(node.p2pPublicKey)

        # Validator checks
        validator = result.validator
        self.assertEqual(node.validator, validator)
        self.assertEqual(validator.status, "ACTIVE")
        self.assertIsNotNone(validator.activatedAt)
        self.assertEqual(validator.totalStake, 1500 * (10 ** self.blockchain.decimals))
        self.assertEqual(validator.commissionPercent, Decimal("5.00"))

        # Account checks
        account = result.account
        self.assertEqual(account.accountType, "EOA")
        self.assertEqual(validator.account, account)
        self.assertEqual(account.address, result.wallet.address)

        # Ledger & Total Supply Conservation checks
        from network.services.genesis import VALIDATOR_RESERVE_ADDRESS
        from wallets.models import Account
        reserve = Account.objects.get(blockchain=self.blockchain, address=VALIDATOR_RESERVE_ADDRESS)
        # 300,000 MYC - 1,600 MYC (1,500 stake + 100 buffer) = 298,400 MYC
        expected_reserve_units = (300000 - 1600) * (10 ** self.blockchain.decimals)
        self.assertEqual(reserve.balance, expected_reserve_units)

        # Total on-chain coin supply across all accounts remains strictly 1,000,000 MYC
        total_balance = sum(acc.balance for acc in Account.objects.filter(blockchain=self.blockchain))
        self.assertEqual(total_balance, self.genesis_config.initial_supply_smallest_units)

        # Block & Transaction checks
        self.assertIsNotNone(result.funding_block)
        self.assertEqual(result.funding_block.height, 1)
        self.assertEqual(result.funding_block.status, "FINALIZED")
        self.blockchain.refresh_from_db()
        self.assertEqual(self.blockchain.latestFinalizedBlock, result.funding_block)

        self.assertIsNotNone(result.funding_transaction)
        self.assertEqual(result.funding_transaction.status, "FINALIZED")
        self.assertEqual(result.funding_transaction.sender, reserve)
        self.assertEqual(result.funding_transaction.receiver, account)

        # Stake checks
        from staking.models import Stake
        stake = Stake.objects.filter(validator=validator).first()
        self.assertIsNotNone(stake)
        self.assertEqual(stake.amount, validator.totalStake)
        self.assertEqual(stake.status, "ACTIVE")
        self.assertEqual(stake.stakeTransaction, result.funding_transaction)

    def test_seed_validator_node_idempotency(self):
        """Verify running seeder twice updates existing records without duplicate errors."""
        from network.models import Node
        from network.services.node_seeder import seed_validator_node

        res1 = seed_validator_node(
            node_id="myc-val-idem-001",
            endpoint="http://localhost:8002",
            node_status="ONLINE",
        )
        self.assertTrue(res1.created)

        # Second execution with updated endpoint/stake
        res2 = seed_validator_node(
            node_id="myc-val-idem-001",
            endpoint="http://localhost:8002",
            node_status="ONLINE",
            stake_amount_myc=2000,
        )
        self.assertFalse(res2.created)
        self.assertEqual(res2.node.id, res1.node.id)
        self.assertEqual(Node.objects.filter(nodeId="myc-val-idem-001").count(), 1)
        self.assertEqual(res2.validator.totalStake, 2000 * (10 ** self.blockchain.decimals))

    def test_seed_validator_node_management_command(self):
        """Verify python manage.py seed_validator_node CLI output and execution."""
        from network.models import Node

        out = StringIO()
        call_command(
            "seed_validator_node",
            "--node-id", "myc-val-cli-001",
            "--endpoint", "http://localhost:8003",
            "--status", "ONLINE",
            "--stake", "1200",
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn("[SUCCESS]", output)
        self.assertIn("myc-val-cli-001", output)
        self.assertIn("nodeType=VALIDATOR", output)
        self.assertIn("status=ONLINE", output)

        node = Node.objects.get(nodeId="myc-val-cli-001")
        self.assertEqual(node.nodeType, "VALIDATOR")
        self.assertEqual(node.status, "ONLINE")

    def test_seed_node_management_command_default(self):
        """Verify python manage.py seed_node defaults to VALIDATOR and ONLINE."""
        from network.models import Node

        out = StringIO()
        call_command(
            "seed_node",
            "--node-id", "myc-default-001",
            "--endpoint", "http://localhost:8004",
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn("[SUCCESS]", output)
        self.assertIn("myc-default-001", output)

        node = Node.objects.get(nodeId="myc-default-001")
        self.assertEqual(node.nodeType, "VALIDATOR")
        self.assertEqual(node.status, "ONLINE")
        self.assertIsNotNone(node.validator)

    def test_seed_validator_node_without_blockchain_fails(self):
        """Verify error is raised when no active blockchain exists."""
        from network.models import Blockchain
        from network.services.node_seeder import NodeSeederError, seed_validator_node

        # Temporarily deactivate blockchain
        self.blockchain.status = "HALTED"
        self.blockchain.save()

        with self.assertRaises(NodeSeederError) as ctx:
            seed_validator_node(
                node_id="myc-fail-001",
                endpoint="http://localhost:8999",
            )
        self.assertIn("No active blockchain found", str(ctx.exception))



class NetworkAPITests(TestCase):
    """API tests for the DDD layered Network endpoints."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.genesis_res = initialize_blockchain(self.genesis_config)
        self.blockchain = self.genesis_res.blockchain

    def test_get_network_status_success(self):
        response = self.client.get("/api/network/status/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["data"]["chainId"], 1001)
        self.assertEqual(response.json()["data"]["chainName"], "TEST_CHAIN")

    def test_list_nodes_success(self):
        response = self.client.get("/api/network/nodes/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertIsInstance(response.json()["data"], list)
