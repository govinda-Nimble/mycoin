"""
Unit and integration tests for network nodes, topology, seeders, and network APIs.
"""

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from chain.models import Blockchain, BlockchainStatus
from chain.services.genesis import GenesisConfig, initialize_blockchain
from network.models import Node, NodeStatus, NodeType


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
            node_status="ONLINE",
            chain_id=1001,
            operator_email="val-operator@mycoin.network",
            stake_amount_myc=1500,
        )

        self.assertTrue(result.created)
        self.assertEqual(result.node.nodeId, "myc-val-node-001")
        self.assertEqual(result.node.nodeType, NodeType.VALIDATOR)
        self.assertEqual(result.node.status, NodeStatus.ONLINE)
        self.assertEqual(result.node.blockchain, self.blockchain)
        self.assertIsNotNone(result.node.validator)

        # Validator checks
        validator = result.validator
        self.assertEqual(validator.totalStake, 1500 * (10 ** self.blockchain.decimals))
        self.assertEqual(validator.status, "ACTIVE")
        self.assertEqual(validator.publicKey, result.wallet.publicKey)

        # Account checks
        account = result.account
        self.assertEqual(account.blockchain, self.blockchain)
        expected_total_units = 1600 * (10 ** self.blockchain.decimals)
        self.assertEqual(account.balance, expected_total_units)
        self.assertEqual(account.address, result.wallet.address)

        # Ledger & Total Supply Conservation checks
        from chain.services.genesis import VALIDATOR_RESERVE_ADDRESS
        from chain.models import Account
        reserve = Account.objects.get(blockchain=self.blockchain, address=VALIDATOR_RESERVE_ADDRESS)
        # 300,000 MYC - 1,600 MYC (1,500 stake + 100 buffer) = 298,400 MYC
        expected_reserve_units = (300000 - 1600) * (10 ** self.blockchain.decimals)
        self.assertEqual(reserve.balance, expected_reserve_units)

        # Total on-chain coin supply across all accounts remains strictly 1,000,000 MYC
        total_balance = sum(acc.balance for acc in Account.objects.filter(blockchain=self.blockchain))
        self.assertEqual(total_balance, 1_000_000 * (10 ** self.blockchain.decimals))

        # Funding Transaction checks
        tx = result.funding_transaction
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, 1600 * (10 ** self.blockchain.decimals))
        self.assertEqual(tx.receiverAddress, account.address)
        self.assertEqual(tx.status, "FINALIZED")

        # Block checks
        block = result.funding_block
        self.assertIsNotNone(block)
        self.assertEqual(block.height, 1)
        self.assertEqual(block.status, "FINALIZED")
        self.blockchain.refresh_from_db()
        self.assertEqual(self.blockchain.latestFinalizedBlock, block)

    def test_idempotent_re_execution_same_node_id(self):
        """Verify calling seed_validator_node multiple times with same node_id is idempotent."""
        from network.services.node_seeder import seed_validator_node

        res1 = seed_validator_node(
            node_id="myc-val-idem-001",
            endpoint="http://localhost:8001",
            chain_id=1001,
        )
        self.assertTrue(res1.created)

        # Second run should update and return existing without creating duplicates
        res2 = seed_validator_node(
            node_id="myc-val-idem-001",
            endpoint="http://localhost:8001",
            chain_id=1001,
        )
        self.assertFalse(res2.created)
        self.assertEqual(res1.node.id, res2.node.id)
        self.assertEqual(res1.validator.id, res2.validator.id)
        self.assertEqual(res1.account.id, res2.account.id)
        self.assertIsNone(res2.funding_transaction)

        # Exactly 1 node with this ID exists
        self.assertEqual(Node.objects.filter(nodeId="myc-val-idem-001").count(), 1)

    def test_seed_node_management_command(self):
        """Verify seed_node management command successfully seeds a node."""
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        call_command(
            "seed_node",
            "--node-id", "myc-default-001",
            "--endpoint", "http://localhost:8001",
            "--node-type", "VALIDATOR",
            "--status", "ONLINE",
            "--chain-id", "1001",
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("Node 'myc-default-001' created successfully", output)
        self.assertIn("nodeType=VALIDATOR", output)
        self.assertIn("status=ONLINE", output)
        self.assertTrue(Node.objects.filter(nodeId="myc-default-001").exists())

    def test_seed_validator_node_management_command(self):
        """Verify seed_validator_node management command successfully seeds a validator node."""
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        call_command(
            "seed_validator_node",
            "--node-id", "myc-val-cli-001",
            "--endpoint", "http://localhost:8002",
            "--status", "ONLINE",
            "--chain-id", "1001",
            "--stake", "1200",
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("Node 'myc-val-cli-001' created successfully", output)
        self.assertIn("Total Stake:      1,200 MYC", output)
        self.assertTrue(Node.objects.filter(nodeId="myc-val-cli-001").exists())


class NetworkAPITests(TestCase):
    """Test suite for Network REST presentation APIs."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_network_status_endpoint(self):
        """Test GET /api/network/status/ returns active network details."""
        config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        initialize_blockchain(config)

        response = self.client.get("/api/network/status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["chainId"], 1001)
        self.assertEqual(response.data["data"]["chainName"], "TEST_CHAIN")

    def test_node_list_endpoint(self):
        """Test GET /api/network/nodes/ returns list of nodes."""
        config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        initialize_blockchain(config)

        response = self.client.get("/api/network/nodes/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIsInstance(response.data["data"], list)
