"""
Comprehensive tests for the Check Transaction validation pipeline,
mempool ingestion, and REST API endpoints.
"""

from datetime import timedelta
from decimal import Decimal
import hashlib
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from ledger.management.commands.run_mempool_processor import Command as MempoolProcessorCommand
from ledger.models import (
    Block,
    BlockStatus,
    MempoolStatus,
    MempoolTransaction,
    Transaction,
    TransactionEvent,
    TransactionReceipt,
    TransactionStatus,
)
from ledger.services.block_producer import (
    approve_single_node_block,
    execute_single_transaction,
    finalize_block,
    prepare_block_proposal,
    produce_block_from_mempool,
    produce_next_block,
    select_transactions_for_block,
    validate_proposed_block,
)
from ledger.services.gossip import gossip_transaction_to_peers, reconcile_block_with_node_mempool
from ledger.services.mempool_processor import (
    DEFAULT_BATCH_SIZE,
    MempoolProcessingResult,
    process_mempool,
    try_acquire_advisory_lock,
)
from ledger.services.transaction_validator import (
    TransactionValidationError,
    validate_and_enqueue_transaction,
)
from network.models import (
    Account,
    AccountStatus,
    AccountType,
    Blockchain,
    BlockchainStatus,
    Node,
    NodePeer,
    NodeType,
    PeerStatus,
)
from network.services.genesis import GenesisConfig, initialize_blockchain
from network.services.node_seeder import seed_validator_node
from wallets.models import Wallet, WalletStatus
from wallets.services.transaction_signer import sign_transaction_payload
from wallets.services.wallet_service import create_wallet_for_user

User = get_user_model()


class CheckTransactionTestCase(TestCase):
    """Test suite verifying each step of the transaction validation pipeline."""

    def setUp(self):
        self.client = APIClient()

        # 1. Initialize Blockchain
        self.genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.genesis_result = initialize_blockchain(self.genesis_config)
        self.blockchain = self.genesis_result.blockchain

        # 2. Seed an active Validator Node for mempool linking
        self.node_result = seed_validator_node(
            node_id="myc-val-001",
            endpoint="http://localhost:8001",
            node_status="ONLINE",
        )
        self.node = self.node_result.node

        # 3. Create Alice (Sender)
        self.alice_user = User.objects.create_user(
            email="alice@test.com",
            firstName="Alice",
            lastName="Sender",
            isEmailVerified=True,
        )
        self.alice_wallet = create_wallet_for_user(self.alice_user, name="Alice Wallet")
        self.alice_account = Account.objects.create(
            blockchain=self.blockchain,
            address=self.alice_wallet.address,
            accountType=AccountType.EOA,
            balance=100_000_000_000,  # 1,000 MYC in 8-decimal base units
            nonce=0,
            status=AccountStatus.ACTIVE,
        )

        # 4. Create Bob (Receiver)
        self.bob_user = User.objects.create_user(
            email="bob@test.com",
            firstName="Bob",
            lastName="Receiver",
            isEmailVerified=True,
        )
        self.bob_wallet = create_wallet_for_user(self.bob_user, name="Bob Wallet")
        self.bob_address = self.bob_wallet.address

    def _sign_tx(
        self,
        amount="2000000000",  # 20 MYC
        nonce=0,
        gas_limit=21000,
        gas_price="2",
        receiver_address=None,
        signing_wallet=None,
    ):
        """Helper to sign a transaction payload using Alice's or a custom wallet."""
        wallet = signing_wallet or self.alice_wallet
        receiver = receiver_address or self.bob_address
        sk = wallet.get_signing_key()

        sig_hex, _ = sign_transaction_payload(
            signing_key=sk,
            chain_id=self.blockchain.chainId,
            sender_address=wallet.address,
            receiver_address=receiver,
            amount=str(amount),
            nonce=int(nonce),
            gas_limit=int(gas_limit),
            gas_price=str(gas_price),
        )

        return {
            "senderAddress": wallet.address,
            "receiverAddress": receiver,
            "amount": str(amount),
            "nonce": int(nonce),
            "gasLimit": int(gas_limit),
            "gasPrice": str(gas_price),
            "publicKey": wallet.publicKey,
            "signature": sig_hex,
        }

    def test_successful_transaction_validation_and_mempool_enqueuing(self):
        """Verify valid transaction passes all 8 checks, saves Transaction as PENDING, and creates Mempool entry."""
        payload = self._sign_tx(amount="2000000000", nonce=0)

        response = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        res_data = response.json()
        self.assertTrue(res_data["success"])
        self.assertEqual(res_data["data"]["status"], "PENDING")
        self.assertEqual(res_data["data"]["mempoolStatus"], "ACTIVE")
        self.assertEqual(res_data["data"]["amount"], "2000000000")
        self.assertEqual(res_data["data"]["nonce"], 0)
        self.assertEqual(res_data["data"]["fee"], 21000 * 2)

        # Verify database records
        clean_hash = res_data["data"]["txHash"].removeprefix("0x")
        tx = Transaction.objects.get(hash=clean_hash)
        self.assertEqual(tx.status, TransactionStatus.PENDING)
        self.assertEqual(tx.sender, self.alice_account)
        self.assertEqual(tx.amount, 2000000000)

        mempool_entry = MempoolTransaction.objects.get(transaction=tx)
        self.assertEqual(mempool_entry.status, MempoolStatus.ACTIVE)
        self.assertEqual(mempool_entry.priority, 2)
        self.assertEqual(mempool_entry.node, self.node)

    def test_check_sender_not_found(self):
        """Check 1: Non-existent sender account is rejected."""
        payload = self._sign_tx()
        payload["senderAddress"] = "0x" + "1" * 40

        response = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_SENDER")

    def test_check_receiver_identical_to_sender(self):
        """Check 2: Self-transfer is rejected."""
        payload = self._sign_tx(receiver_address=self.alice_wallet.address)

        response = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_RECEIVER")

    def test_verify_public_key_mismatch(self):
        """Check 3: Public key not deriving sender address is rejected."""
        payload = self._sign_tx()
        # Tamper public key with Bob's public key
        payload["publicKey"] = self.bob_wallet.publicKey

        response = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "VERIFY_PUBLIC_KEY")

    def test_verify_signature_tampered(self):
        """Check 4: Tampered amount or invalid signature is rejected."""
        payload = self._sign_tx(amount="2000000000")
        # Tamper amount after signing
        payload["amount"] = "9999999999"

        response = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "VERIFY_SIGNATURE")

    def test_check_nonce_too_low(self):
        """Check 5: Nonce lower than account nonce is rejected."""
        self.alice_account.nonce = 5
        self.alice_account.save()

        payload = self._sign_tx(nonce=2)

        response = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_NONCE")
        self.assertIn("Nonce too low", response.json()["reason"])

    def test_check_nonce_conflict_live_tx(self):
        """Check 5: Duplicate nonce on live transaction is rejected."""
        payload1 = self._sign_tx(nonce=0)
        res1 = self.client.post("/api/ledger/transactions/validate/", payload1, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Another transaction with different amount but same nonce 0
        payload2 = self._sign_tx(amount="3000000000", nonce=0)
        res2 = self.client.post("/api/ledger/transactions/validate/", payload2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res2.json()["step"], "CHECK_NONCE")
        self.assertIn("Nonce conflict", res2.json()["reason"])

    def test_check_balance_insufficient(self):
        """Check 6: Insufficient balance is rejected."""
        # Alice only has 1,000 MYC (100,000,000,000 units), try to send 2,000 MYC
        payload = self._sign_tx(amount="200000000000")

        response = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_BALANCE")
        self.assertIn("Insufficient balance", response.json()["reason"])

    def test_check_gas_limit_below_base(self):
        """Check 7: Gas limit below baseTransferGas is rejected."""
        # baseTransferGas is 21000
        payload = self._sign_tx(gas_limit=10000)

        response = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_GAS")
        self.assertIn("below minimum base transfer gas", response.json()["reason"])

    def test_check_duplicate_hash(self):
        """Check 8: Submitting identical transaction payload twice is rejected."""
        payload = self._sign_tx(nonce=0)

        res1 = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Submit identical payload again
        res2 = self.client.post("/api/ledger/transactions/validate/", payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        # It gets caught as nonce conflict or duplicate hash
        self.assertIn(res2.json()["step"], ["CHECK_NONCE", "CHECK_DUPLICATE_HASH"])

    def test_endpoint_aliases(self):
        """Verify API is accessible via all configured alias endpoints."""
        endpoints = [
            "/api/ledger/transactions/validate/",
            "/api/wallets/transactions/validate/",
        ]
        for idx, ep in enumerate(endpoints):
            payload = self._sign_tx(nonce=idx, amount=str((idx + 1) * 100000000))
            res = self.client.post(ep, payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_201_CREATED, f"Failed at endpoint {ep}")


class MempoolProcessorTestCase(TestCase):
    """
    Test suite for the MYCOIN Mempool Processor:
    - Service function: process_mempool
    - Management command: run_mempool_processor
    - Concurrency protection: PostgreSQL advisory locks & row-level select_for_update
    - Robustness & exception handling
    """

    def setUp(self):
        # 1. Initialize Blockchain
        self.genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.genesis_result = initialize_blockchain(self.genesis_config)
        self.blockchain = self.genesis_result.blockchain

        # 2. Seed active Validator Node
        self.node_result = seed_validator_node(
            node_id="myc-val-node-001",
            endpoint="http://localhost:8001",
            node_status="ONLINE",
        )
        self.node = self.node_result.node

        # 3. Create Sender User and Account
        self.alice_user = User.objects.create_user(
            email="alice_mempool@test.com",
            firstName="Alice",
            lastName="Sender",
            isEmailVerified=True,
        )
        self.alice_wallet = create_wallet_for_user(self.alice_user, name="Alice Mempool Wallet")
        self.alice_account = Account.objects.create(
            blockchain=self.blockchain,
            address=self.alice_wallet.address,
            accountType=AccountType.EOA,
            balance=100_000_000_000,
            nonce=0,
            status=AccountStatus.ACTIVE,
        )

        # 4. Create Receiver
        self.bob_user = User.objects.create_user(
            email="bob_mempool@test.com",
            firstName="Bob",
            lastName="Receiver",
            isEmailVerified=True,
        )
        self.bob_wallet = create_wallet_for_user(self.bob_user, name="Bob Mempool Wallet")
        self.bob_address = self.bob_wallet.address

    def _create_mempool_tx(
        self,
        tx_hash: str,
        nonce: int = 0,
        amount: int = 100_000_000,
        gas_limit: int = 21000,
        gas_price: int = 2,
        priority: int = 2,
        tx_status: str = TransactionStatus.PENDING,
        mempool_status: str = MempoolStatus.ACTIVE,
        blockchain=None,
        sender=None,
        receiver_address=None,
        node=None,
        arrival_time=None,
        expires_at=None,
    ) -> MempoolTransaction:
        chain = blockchain or self.blockchain
        sndr = sender or self.alice_account
        rcvr = receiver_address or self.bob_address
        nd = node or self.node

        now = timezone.now()
        arrival = arrival_time or now
        expires = expires_at or (arrival + timedelta(hours=1))

        tx = Transaction.objects.create(
            hash=tx_hash,
            blockchain=chain,
            sender=sndr,
            receiverAddress=rcvr,
            amount=amount,
            nonce=nonce,
            gasLimit=gas_limit,
            gasPrice=gas_price,
            status=tx_status,
            signature="a" * 128,
            publicKey="04" + "b" * 126,
        )
        mtx = MempoolTransaction.objects.create(
            transaction=tx,
            node=nd,
            priority=priority,
            arrivalTime=arrival,
            expiresAt=expires,
            status=mempool_status,
        )
        return mtx

    def test_management_command_starts_and_single_run(self):
        """1. Management command starts cleanly and completes in single-run mode."""
        out = StringIO()
        call_command("run_mempool_processor", single_run=True, stdout=out)
        output = out.getvalue()
        self.assertIn("MYCOIN Mempool Processor Started", output)
        self.assertIn("Single-run completed", output)
        self.assertIn("MYCOIN Mempool Processor Stopped cleanly", output)

    def test_empty_mempool_handling(self):
        """2. When mempool is empty, process_mempool returns EMPTY status without errors."""
        result = process_mempool(blockchain=self.blockchain)
        self.assertEqual(result.status, "EMPTY")
        self.assertEqual(result.total_eligible_count, 0)
        self.assertEqual(result.selected_count, 0)
        self.assertEqual(len(result.transactions), 0)
        self.assertIn("Mempool is empty", result.message)

    def test_active_mempool_transactions_detected(self):
        """3. Active pending transactions are successfully queried, selected, and packaged into a block."""
        h1 = hashlib.sha256(b"tx_active_1").hexdigest()
        h2 = hashlib.sha256(b"tx_active_2").hexdigest()
        tx1 = self._create_mempool_tx(tx_hash=h1, nonce=0, priority=5)
        tx2 = self._create_mempool_tx(tx_hash=h2, nonce=1, priority=10)

        result = process_mempool(blockchain=self.blockchain)
        self.assertIn(result.status, ["BATCH_PROCESSED", "BATCH_SELECTED"])
        self.assertEqual(result.total_eligible_count, 2)
        self.assertEqual(result.selected_count, 2)
        self.assertIsNotNone(result.produced_block_height)

        # Verify MempoolTransactions were marked INCLUDED
        self.assertEqual(MempoolTransaction.objects.get(id=tx1.id).status, MempoolStatus.INCLUDED)
        self.assertEqual(MempoolTransaction.objects.get(id=tx2.id).status, MempoolStatus.INCLUDED)

        # Verify Transactions were marked FINALIZED and assigned to the block
        t1 = Transaction.objects.get(id=tx1.transaction_id)
        self.assertEqual(t1.status, TransactionStatus.FINALIZED)
        self.assertEqual(t1.block.height, result.produced_block_height)

        # Verify that subsequent cycle reports mempool as EMPTY (no continuous duplicate processing)
        cycle2 = process_mempool(blockchain=self.blockchain)
        self.assertEqual(cycle2.status, "EMPTY")
        self.assertEqual(cycle2.total_eligible_count, 0)

    def test_expired_transactions_ignored(self):
        """4. Expired mempool transactions (expiresAt <= now) are filtered out."""
        now = timezone.now()
        h_valid = hashlib.sha256(b"tx_valid").hexdigest()
        h_expired = hashlib.sha256(b"tx_expired").hexdigest()

        tx_valid = self._create_mempool_tx(tx_hash=h_valid, nonce=0, priority=5)
        self._create_mempool_tx(
            tx_hash=h_expired,
            nonce=1,
            priority=10,
            arrival_time=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )

        result = process_mempool(blockchain=self.blockchain)
        self.assertEqual(result.total_eligible_count, 1)
        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.transactions[0].id, tx_valid.id)

    def test_invalid_transaction_statuses_ignored(self):
        """5. Ineligible transaction or mempool statuses are ignored."""
        h1 = hashlib.sha256(b"tx_included").hexdigest()
        h2 = hashlib.sha256(b"tx_expired").hexdigest()
        h3 = hashlib.sha256(b"tx_dropped").hexdigest()

        self._create_mempool_tx(tx_hash=h1, nonce=0, mempool_status=MempoolStatus.INCLUDED)
        self._create_mempool_tx(tx_hash=h2, nonce=1, mempool_status=MempoolStatus.EXPIRED)
        self._create_mempool_tx(tx_hash=h3, nonce=2, tx_status=TransactionStatus.DROPPED)

        result = process_mempool(blockchain=self.blockchain)
        self.assertEqual(result.status, "EMPTY")
        self.assertEqual(result.total_eligible_count, 0)
        self.assertEqual(result.selected_count, 0)

    def test_correct_blockchain_filtering(self):
        """6. Transactions belonging to another blockchain are strictly filtered out."""
        genesis2 = initialize_blockchain(GenesisConfig(chain_id=2002, chain_name="OTHER_CHAIN"))
        other_chain = genesis2.blockchain

        other_account = Account.objects.create(
            blockchain=other_chain,
            address=self.alice_wallet.address,
            accountType=AccountType.EOA,
            balance=100_000_000,
            nonce=0,
            status=AccountStatus.ACTIVE,
        )
        other_node_res = seed_validator_node(
            node_id="other-val-node-001",
            endpoint="http://localhost:8002",
            node_status="ONLINE",
            chain_id=2002,
        )
        h_other = hashlib.sha256(b"tx_other_chain").hexdigest()
        self._create_mempool_tx(
            tx_hash=h_other,
            nonce=0,
            blockchain=other_chain,
            sender=other_account,
            node=other_node_res.node,
        )

        result = process_mempool(blockchain=self.blockchain)
        self.assertEqual(result.status, "EMPTY")
        self.assertEqual(result.total_eligible_count, 0)

    def test_batch_size_respected(self):
        """7. Batch size limit and priority sorting (highest fee first) are respected."""
        for idx, prio in enumerate([5, 50, 20, 10]):
            user = User.objects.create_user(email=f"sender_batch_{idx}@test.com", firstName=f"S{idx}", lastName="Batch", isEmailVerified=True)
            w = create_wallet_for_user(user, name=f"Batch Wallet {idx}")
            acc = Account.objects.create(
                blockchain=self.blockchain,
                address=w.address,
                balance=100_000_000_000,
                nonce=0,
                status=AccountStatus.ACTIVE,
            )
            h = hashlib.sha256(f"tx_batch_{idx}".encode()).hexdigest()
            self._create_mempool_tx(tx_hash=h, sender=acc, nonce=0, priority=prio, gas_price=prio)

        result = process_mempool(blockchain=self.blockchain, batch_size=2)
        self.assertEqual(result.total_eligible_count, 4)
        self.assertEqual(result.selected_count, 2)
        self.assertEqual(result.transactions[0].priority, 50)
        self.assertEqual(result.transactions[1].priority, 20)

    def test_duplicate_processing_protection_skip_locked(self):
        """8. Concurrency protection handles locked candidate rows by returning LOCK_UNAVAILABLE if all candidates are locked."""
        h1 = hashlib.sha256(b"tx_lock_1").hexdigest()
        self._create_mempool_tx(tx_hash=h1, nonce=0, priority=10)

        # Mock select_for_update returning an empty list to simulate all rows locked by a concurrent worker
        with patch("django.db.models.query.QuerySet.select_for_update") as mock_sfu:
            mock_sfu.return_value.select_related.return_value.order_by.return_value = MempoolTransaction.objects.none()
            result = process_mempool(blockchain=self.blockchain)
            self.assertEqual(result.status, "LOCK_UNAVAILABLE")
            self.assertEqual(result.selected_count, 0)
            self.assertIn("locked by another concurrent process", result.message)

    def test_lock_acquisition_failure_handling(self):
        """9. When advisory lock is already held by another worker, process_mempool skips cycle safely."""
        with patch("ledger.services.mempool_processor.try_acquire_advisory_lock", return_value=False):
            result = process_mempool(blockchain=self.blockchain)
            self.assertEqual(result.status, "LOCK_UNAVAILABLE")
            self.assertEqual(result.selected_count, 0)
            self.assertIn("Processor lock is currently held", result.message)

    def test_unexpected_service_exception_resilience(self):
        """10. Management command loop does not crash on unexpected exceptions in processing service."""
        out = StringIO()
        err = StringIO()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Temporary DB connectivity error")
            return MempoolProcessingResult(status="EMPTY", message="Recovered in second cycle")

        with patch("ledger.management.commands.run_mempool_processor.process_mempool", side_effect=side_effect):
            call_command("run_mempool_processor", interval=0, max_iterations=2, stdout=out, stderr=err)

        self.assertIn("Temporary DB connectivity error", err.getvalue())
        self.assertIn("Total cycles executed: 2", out.getvalue())

    def test_graceful_shutdown_on_interrupt(self):
        """11. Management command terminates cleanly when interrupt signal / stop_event is triggered."""
        cmd = MempoolProcessorCommand()
        out = StringIO()
        cmd.stdout = out

        def mock_process(*args, **kwargs):
            cmd.stop_event.set()
            return MempoolProcessingResult(status="EMPTY")

        with patch("ledger.management.commands.run_mempool_processor.process_mempool", side_effect=mock_process):
            cmd.handle(interval=0, batch_size=50, chain_id=None, single_run=False, max_iterations=None)

        output = out.getvalue()
        self.assertIn("MYCOIN Mempool Processor Stopped cleanly", output)
        self.assertIn("Total cycles executed: 1", output)


class NodeSpecificMempoolNonceConflictTests(TestCase):
    """
    Comprehensive test suite verifying Node-Specific Mempool Nonce Conflict Management:
    1. Permanent storage allows competing signed transactions with the same sender and nonce.
    2. Node-level active mempool uniqueness for (node, sender, nonce).
    3. Multi-node independence: Node A can hold TX001 active while Node B holds TX002 active.
    4. Duplicate transaction gossip handled idempotently.
    5. Replacement policy accepts higher gas price and deactivates lower gas price.
    6. Replacement policy rejects lower/equal gas price without creating a second active entry.
    7. Block finalization marks winning transaction finalized and updates sender account nonce.
    8. Block finalization reconciles mempools across nodes by marking competing transactions REPLACED/DROPPED.
    9. Block finalization removes finalized and competing transactions from active mempools.
    10. Sequential transactions with different nonces can be queued concurrently.
    11. Expired or dropped mempool transactions do not block a new active transaction with that nonce.
    12. Multi-node canonical state convergence.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Drop partial index on test DB if present to allow competing transactions in Transaction model
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX IF EXISTS chain_tx_unique_sender_nonce_live;")

    def setUp(self):
        # 1. Initialize Blockchain
        self.genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.genesis_result = initialize_blockchain(self.genesis_config)
        self.blockchain = self.genesis_result.blockchain

        # 2. Seed Node A (Validator)
        self.node_a_res = seed_validator_node(
            node_id="node-a-validator",
            endpoint="http://localhost:8001",
            node_status="ONLINE",
        )
        self.node_a = self.node_a_res.node

        # 3. Seed Node B (Full Node)
        self.node_b = Node.objects.create(
            blockchain=self.blockchain,
            nodeId="node-b-full",
            nodeType=NodeType.FULL,
            endpoint="http://localhost:8002",
            status="ONLINE",
        )

        # 4. Peer connection from Node A to Node B
        self.peer_a_b = NodePeer.objects.create(
            localNode=self.node_a,
            peerNode=self.node_b,
            status=PeerStatus.CONNECTED,
        )

        # 5. Create Alice (Sender) with 1,000 MYC
        self.alice_user = User.objects.create_user(
            email="alice_nonce@test.com",
            firstName="Alice",
            lastName="Nonce",
            isEmailVerified=True,
        )
        self.alice_wallet = create_wallet_for_user(self.alice_user, name="Alice Nonce Wallet")
        self.alice_account = Account.objects.create(
            blockchain=self.blockchain,
            address=self.alice_wallet.address,
            accountType=AccountType.EOA,
            balance=100_000_000_000,
            nonce=0,
            status=AccountStatus.ACTIVE,
        )

        # 6. Create Bob (Receiver 1) & Charlie (Receiver 2)
        self.bob_user = User.objects.create_user(
            email="bob_nonce@test.com",
            firstName="Bob",
            lastName="Nonce",
            isEmailVerified=True,
        )
        self.bob_wallet = create_wallet_for_user(self.bob_user, name="Bob Nonce Wallet")
        self.bob_address = self.bob_wallet.address

        self.charlie_user = User.objects.create_user(
            email="charlie_nonce@test.com",
            firstName="Charlie",
            lastName="Nonce",
            isEmailVerified=True,
        )
        self.charlie_wallet = create_wallet_for_user(self.charlie_user, name="Charlie Nonce Wallet")
        self.charlie_address = self.charlie_wallet.address

    def _sign_tx(self, amount="1000000000", nonce=0, gas_price="2", receiver=None):
        target_receiver = receiver or self.bob_address
        sk = self.alice_wallet.get_signing_key()
        sig_hex, _ = sign_transaction_payload(
            signing_key=sk,
            chain_id=self.blockchain.chainId,
            sender_address=self.alice_wallet.address,
            receiver_address=target_receiver,
            amount=str(amount),
            nonce=int(nonce),
            gas_limit=21000,
            gas_price=str(gas_price),
        )
        return {
            "senderAddress": self.alice_wallet.address,
            "receiverAddress": target_receiver,
            "amount": str(amount),
            "nonce": int(nonce),
            "gasLimit": 21000,
            "gasPrice": str(gas_price),
            "publicKey": self.alice_wallet.publicKey,
            "signature": sig_hex,
        }

    def test_01_two_different_signed_transactions_with_same_sender_and_nonce_accepted_into_permanent_storage(self):
        """1. Two different signed transactions with same sender and nonce accepted into permanent storage."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0, receiver=self.bob_address)
        tx2_payload = self._sign_tx(amount="2000000000", nonce=0, receiver=self.charlie_address)

        res1 = validate_and_enqueue_transaction(tx1_payload, node=self.node_a)
        res2 = validate_and_enqueue_transaction(tx2_payload, node=self.node_b)

        self.assertNotEqual(res1.tx_hash, res2.tx_hash)
        stored_txs = Transaction.objects.filter(sender=self.alice_account, nonce=0)
        self.assertEqual(stored_txs.count(), 2)

    def test_02_individual_node_allows_only_one_active_mempool_transaction_for_sender_nonce(self):
        """2. An individual node allows only one active mempool transaction for a given (sender, nonce)."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0, gas_price="2", receiver=self.bob_address)
        tx2_payload = self._sign_tx(amount="2000000000", nonce=0, gas_price="2", receiver=self.charlie_address)

        validate_and_enqueue_transaction(tx1_payload, node=self.node_a)

        with self.assertRaises(TransactionValidationError) as ctx:
            validate_and_enqueue_transaction(tx2_payload, node=self.node_a)

        self.assertEqual(ctx.exception.step, "CHECK_NONCE")
        self.assertIn("Nonce conflict", ctx.exception.message)

        active_count = MempoolTransaction.objects.filter(
            node=self.node_a,
            transaction__sender=self.alice_account,
            transaction__nonce=0,
            status=MempoolStatus.ACTIVE,
        ).count()
        self.assertEqual(active_count, 1)

    def test_03_node_a_holds_tx1_active_while_node_b_holds_tx2_active_for_same_sender_and_nonce(self):
        """3. Node A holds TX001 active while Node B holds TX002 active for the same sender and nonce."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0, receiver=self.bob_address)
        tx2_payload = self._sign_tx(amount="2000000000", nonce=0, receiver=self.charlie_address)

        res1 = validate_and_enqueue_transaction(tx1_payload, node=self.node_a)
        res2 = validate_and_enqueue_transaction(tx2_payload, node=self.node_b)

        active_a = MempoolTransaction.objects.get(
            node=self.node_a,
            transaction__sender=self.alice_account,
            transaction__nonce=0,
            status=MempoolStatus.ACTIVE,
        )
        active_b = MempoolTransaction.objects.get(
            node=self.node_b,
            transaction__sender=self.alice_account,
            transaction__nonce=0,
            status=MempoolStatus.ACTIVE,
        )

        self.assertEqual(active_a.transaction_id, res1.transaction.id)
        self.assertEqual(active_b.transaction_id, res2.transaction.id)
        self.assertNotEqual(active_a.transaction_id, active_b.transaction_id)

    def test_04_duplicate_transaction_gossip_handled_idempotently(self):
        """4. Duplicate transaction gossip is ignored or handled idempotently without creating duplicate active entries."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx1_payload, node=self.node_a)

        # Gossip to Node B for the first time
        res1 = gossip_transaction_to_peers(tx1_payload, source_node=self.node_a)
        self.assertEqual(res1[self.node_b.nodeId]["status"], "accepted")

        # Gossip same transaction again
        res2 = gossip_transaction_to_peers(tx1_payload, source_node=self.node_a)
        self.assertEqual(res2[self.node_b.nodeId]["status"], "duplicate")

        # Node B must still have exactly 1 mempool transaction
        count_b = MempoolTransaction.objects.filter(
            node=self.node_b,
            transaction__sender=self.alice_account,
            transaction__nonce=0,
        ).count()
        self.assertEqual(count_b, 1)

    def test_05_replacement_policy_accepts_higher_fee_and_deactivates_lower_fee(self):
        """5. Replacement policy accepts higher gas price and deactivates lower gas price."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0, gas_price="2")
        tx2_payload = self._sign_tx(amount="1500000000", nonce=0, gas_price="5", receiver=self.charlie_address)

        res1 = validate_and_enqueue_transaction(tx1_payload, node=self.node_a)
        res2 = validate_and_enqueue_transaction(tx2_payload, node=self.node_a)

        res1.mempool_entry.refresh_from_db()
        self.assertEqual(res1.mempool_entry.status, MempoolStatus.REPLACED)

        res2.mempool_entry.refresh_from_db()
        self.assertEqual(res2.mempool_entry.status, MempoolStatus.ACTIVE)

        active_count = MempoolTransaction.objects.filter(
            node=self.node_a,
            transaction__sender=self.alice_account,
            transaction__nonce=0,
            status=MempoolStatus.ACTIVE,
        ).count()
        self.assertEqual(active_count, 1)

    def test_06_replacement_policy_rejects_lower_or_equal_fee_without_second_active_entry(self):
        """6. Replacement policy rejects lower or equal fee without creating a second active entry."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0, gas_price="5")
        tx2_payload = self._sign_tx(amount="1500000000", nonce=0, gas_price="2", receiver=self.charlie_address)

        res1 = validate_and_enqueue_transaction(tx1_payload, node=self.node_a)

        with self.assertRaises(TransactionValidationError) as ctx:
            validate_and_enqueue_transaction(tx2_payload, node=self.node_a)

        self.assertIn("Nonce conflict", ctx.exception.message)

        # tx1 remains active
        res1.mempool_entry.refresh_from_db()
        self.assertEqual(res1.mempool_entry.status, MempoolStatus.ACTIVE)

        # tx2 is retained in permanent storage but not active
        self.assertTrue(Transaction.objects.filter(sender=self.alice_account, amount=1500000000).exists())
        active_count = MempoolTransaction.objects.filter(
            node=self.node_a,
            transaction__sender=self.alice_account,
            transaction__nonce=0,
            status=MempoolStatus.ACTIVE,
        ).count()
        self.assertEqual(active_count, 1)

    def test_07_block_finalization_marks_tx_finalized_and_updates_account_nonce(self):
        """7. Finalization of a block with TX001 marks TX001 finalized and updates sender account nonce."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0)
        res1 = validate_and_enqueue_transaction(tx1_payload, node=self.node_a)

        block = produce_block_from_mempool(self.blockchain, [res1.mempool_entry])
        self.assertIsNotNone(block)

        self.alice_account.refresh_from_db()
        self.assertEqual(self.alice_account.nonce, 1)

        res1.transaction.refresh_from_db()
        self.assertEqual(res1.transaction.status, TransactionStatus.FINALIZED)

    def test_08_block_finalization_marks_competing_tx_as_replaced_dropped_across_nodes(self):
        """8. Block finalization marks competing TX002 as replaced/dropped across nodes."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0, receiver=self.bob_address)
        tx2_payload = self._sign_tx(amount="2000000000", nonce=0, receiver=self.charlie_address)

        res1 = validate_and_enqueue_transaction(tx1_payload, node=self.node_a)
        res2 = validate_and_enqueue_transaction(tx2_payload, node=self.node_b)

        produce_block_from_mempool(self.blockchain, [res1.mempool_entry])

        res2.mempool_entry.refresh_from_db()
        self.assertEqual(res2.mempool_entry.status, MempoolStatus.REPLACED)

        res2.transaction.refresh_from_db()
        self.assertEqual(res2.transaction.status, TransactionStatus.DROPPED)

    def test_09_block_finalization_removes_finalized_and_competing_from_active_mempools(self):
        """9. Block finalization removes finalized and competing transactions from active mempools."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0, receiver=self.bob_address)
        tx2_payload = self._sign_tx(amount="2000000000", nonce=0, receiver=self.charlie_address)

        res1 = validate_and_enqueue_transaction(tx1_payload, node=self.node_a)
        res2 = validate_and_enqueue_transaction(tx2_payload, node=self.node_b)

        produce_block_from_mempool(self.blockchain, [res1.mempool_entry])

        active_entries = MempoolTransaction.objects.filter(
            transaction__sender=self.alice_account,
            transaction__nonce=0,
            status=MempoolStatus.ACTIVE,
        )
        self.assertEqual(active_entries.count(), 0)

    def test_10_valid_transactions_with_different_nonces_queued_concurrently(self):
        """10. Valid transactions with different nonces from the same sender can be queued concurrently."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        tx1 = self._sign_tx(amount="1000000000", nonce=1)
        tx2 = self._sign_tx(amount="1000000000", nonce=2)

        res0 = validate_and_enqueue_transaction(tx0, node=self.node_a)
        res1 = validate_and_enqueue_transaction(tx1, node=self.node_a)
        res2 = validate_and_enqueue_transaction(tx2, node=self.node_a)

        self.assertEqual(res0.mempool_entry.status, MempoolStatus.ACTIVE)
        self.assertEqual(res1.mempool_entry.status, MempoolStatus.ACTIVE)
        self.assertEqual(res2.mempool_entry.status, MempoolStatus.ACTIVE)

        active_count = MempoolTransaction.objects.filter(
            node=self.node_a,
            transaction__sender=self.alice_account,
            status=MempoolStatus.ACTIVE,
        ).count()
        self.assertEqual(active_count, 3)

    def test_11_expired_or_dropped_mempool_transaction_does_not_block_new_active_transaction(self):
        """11. Expired or dropped mempool transactions do not block a new active transaction with that nonce."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0, receiver=self.bob_address)
        res1 = validate_and_enqueue_transaction(tx1_payload, node=self.node_a)

        # Mark existing mempool entry as EXPIRED and tx as DROPPED
        res1.mempool_entry.status = MempoolStatus.EXPIRED
        res1.mempool_entry.save(update_fields=["status", "updatedAt"])
        res1.transaction.status = TransactionStatus.DROPPED
        res1.transaction.save(update_fields=["status", "updatedAt"])

        # Submit new transaction with same nonce 0
        tx2_payload = self._sign_tx(amount="2000000000", nonce=0, receiver=self.charlie_address)
        res2 = validate_and_enqueue_transaction(tx2_payload, node=self.node_a)

        self.assertEqual(res2.mempool_entry.status, MempoolStatus.ACTIVE)

    def test_12_multi_node_block_processing_produces_identical_canonical_state(self):
        """12. Multi-node block processing produces identical canonical state across all nodes."""
        tx1_payload = self._sign_tx(amount="1000000000", nonce=0, receiver=self.bob_address)
        tx2_payload = self._sign_tx(amount="2000000000", nonce=0, receiver=self.charlie_address)

        res1 = validate_and_enqueue_transaction(tx1_payload, node=self.node_a)
        res2 = validate_and_enqueue_transaction(tx2_payload, node=self.node_b)

        # Node A produces and finalizes the block
        block = produce_block_from_mempool(self.blockchain, [res1.mempool_entry])

        # Node B reconciles its local mempool against the finalized block
        reconcile_res = reconcile_block_with_node_mempool(self.node_b, block)
        self.assertEqual(reconcile_res["replaced"], 1)

        # Neither node has active entries for nonce 0
        self.assertFalse(
            MempoolTransaction.objects.filter(
                node=self.node_a,
                transaction__nonce=0,
                status=MempoolStatus.ACTIVE,
            ).exists()
        )
        self.assertFalse(
            MempoolTransaction.objects.filter(
                node=self.node_b,
                transaction__nonce=0,
                status=MempoolStatus.ACTIVE,
            ).exists()
        )


class BlockProductionFlowStages4To14Tests(TestCase):
    """
    Unit test suite covering the full Block Production and Finalization Flow (Stages 4–14).
    Verifies all 20 required scenarios specified in Section 14.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX IF EXISTS chain_tx_unique_sender_nonce_live;")

    def setUp(self):
        self.genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.genesis_result = initialize_blockchain(self.genesis_config)
        self.blockchain = self.genesis_result.blockchain

        self.node_res = seed_validator_node(
            node_id="val-node-bp-001",
            endpoint="http://localhost:8001",
            node_status="ONLINE",
        )
        self.node = self.node_res.node
        self.validator = self.node_res.validator

        self.alice_user = User.objects.create_user(
            email="alice_bp@test.com", firstName="Alice", lastName="BP", isEmailVerified=True
        )
        self.alice_wallet = create_wallet_for_user(self.alice_user, name="Alice BP Wallet")
        self.alice_account = Account.objects.create(
            blockchain=self.blockchain,
            address=self.alice_wallet.address,
            accountType=AccountType.EOA,
            balance=100_000_000_000,
            nonce=0,
            status=AccountStatus.ACTIVE,
        )

        self.bob_user = User.objects.create_user(
            email="bob_bp@test.com", firstName="Bob", lastName="BP", isEmailVerified=True
        )
        self.bob_wallet = create_wallet_for_user(self.bob_user, name="Bob BP Wallet")
        self.bob_address = self.bob_wallet.address

    def _sign_tx(self, amount="1000000000", nonce=0, gas_price="2", receiver=None):
        target = receiver or self.bob_address
        sk = self.alice_wallet.get_signing_key()
        sig_hex, _ = sign_transaction_payload(
            signing_key=sk,
            chain_id=self.blockchain.chainId,
            sender_address=self.alice_wallet.address,
            receiver_address=target,
            amount=str(amount),
            nonce=int(nonce),
            gas_limit=21000,
            gas_price=str(gas_price),
        )
        return {
            "senderAddress": self.alice_wallet.address,
            "receiverAddress": target,
            "amount": str(amount),
            "nonce": int(nonce),
            "gasLimit": 21000,
            "gasPrice": str(gas_price),
            "publicKey": self.alice_wallet.publicKey,
            "signature": sig_hex,
        }

    def test_01_eligible_transactions_selected_correctly(self):
        """1. Eligible transactions are selected correctly from the mempool."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        tx1 = self._sign_tx(amount="2000000000", nonce=1)
        validate_and_enqueue_transaction(tx0, node=self.node)
        validate_and_enqueue_transaction(tx1, node=self.node)

        selected = select_transactions_for_block(self.blockchain, node=self.node)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].transaction.nonce, 0)
        self.assertEqual(selected[1].transaction.nonce, 1)

    def test_02_invalid_transactions_not_selected(self):
        """2. Invalid transactions (e.g. invalid signature) are not selected."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        res0 = validate_and_enqueue_transaction(tx0, node=self.node)

        # Corrupt the signature of the transaction in the database
        res0.transaction.signature = "12345678" * 16
        res0.transaction.save(update_fields=["signature"])

        selected = select_transactions_for_block(self.blockchain, node=self.node)
        self.assertEqual(len(selected), 0)

    def test_03_transactions_with_incorrect_nonce_ordering_not_executed(self):
        """3. Transactions with incorrect nonce ordering (nonce gap) are not selected."""
        # Sender submits nonce 0
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx0, node=self.node)

        # Alice's account nonce is currently 0. Submitting nonce 2 directly via DB (simulating a gap)
        tx2_payload = self._sign_tx(amount="1000000000", nonce=2)
        # Create un-ordered mempool transaction directly
        tx2 = Transaction.objects.create(
            blockchain=self.blockchain,
            hash=hashlib.sha256(b"tx_gap_2").hexdigest(),
            sender=self.alice_account,
            receiverAddress=self.bob_address,
            amount=1000000000,
            nonce=2,
            gasLimit=21000,
            gasPrice=2,
            publicKey=self.alice_wallet.publicKey,
            signature=tx2_payload["signature"],
            status=TransactionStatus.PENDING,
        )
        MempoolTransaction.objects.create(
            transaction=tx2,
            node=self.node,
            priority=2,
            arrivalTime=timezone.now(),
            expiresAt=timezone.now() + timezone.timedelta(hours=2),
            status=MempoolStatus.ACTIVE,
        )

        selected = select_transactions_for_block(self.blockchain, node=self.node)
        # Only nonce 0 can be selected; nonce 2 is skipped due to the missing nonce 1
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].transaction.nonce, 0)

    def test_04_block_gas_limit_respected(self):
        """4. Block gas limit is strictly respected during selection."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        tx1 = self._sign_tx(amount="1000000000", nonce=1)
        validate_and_enqueue_transaction(tx0, node=self.node)
        validate_and_enqueue_transaction(tx1, node=self.node)

        # Max gas 30,000: only 1 tx of 21,000 gas can fit
        selected = select_transactions_for_block(self.blockchain, node=self.node, max_gas=30000)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].transaction.gasLimit, 21000)

    def test_05_block_height_and_parent_hash_correct(self):
        """5. Block height and parent hash are computed correctly in proposal."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx0, node=self.node)

        parent = Block.objects.filter(blockchain=self.blockchain, status=BlockStatus.FINALIZED).order_by("-height").first()
        selected = select_transactions_for_block(self.blockchain, node=self.node)
        proposal = prepare_block_proposal(self.blockchain, selected_entries=selected)

        self.assertEqual(proposal.height, parent.height + 1)
        self.assertEqual(proposal.previousHash, parent.blockHash)
        self.assertEqual(proposal.status, BlockStatus.PROPOSED)

    def test_06_invalid_block_proposals_cannot_be_finalized(self):
        """6. Invalid block proposals cannot be finalized and are rejected."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx0, node=self.node)
        selected = select_transactions_for_block(self.blockchain, node=self.node)
        proposal = prepare_block_proposal(self.blockchain, selected_entries=selected)

        # Tamper with proposal previousHash
        proposal.previousHash = "0" * 64
        proposal.save(update_fields=["previousHash"])

        is_valid, reason = validate_proposed_block(proposal)
        self.assertFalse(is_valid)
        self.assertIn("does not match parent blockHash", reason)

        approved = approve_single_node_block(proposal)
        self.assertFalse(approved)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, BlockStatus.REJECTED)

    def test_07_valid_block_finalizes_successfully(self):
        """7. A valid block finalizes successfully."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx0, node=self.node)
        selected = select_transactions_for_block(self.blockchain, node=self.node)
        proposal = prepare_block_proposal(self.blockchain, selected_entries=selected)

        self.assertTrue(approve_single_node_block(proposal))
        finalized = finalize_block(proposal, selected_entries=selected)

        self.assertEqual(finalized.status, BlockStatus.FINALIZED)
        self.assertIsNotNone(finalized.finalizedAt)

    def test_08_account_balances_updated_correctly(self):
        """8. Account balances are updated correctly upon block finalization."""
        initial_balance = self.alice_account.balance
        amount = 10_000_000_000  # 100 MYC
        fee = 21000 * 2  # 42,000 units
        tx0 = self._sign_tx(amount=str(amount), nonce=0, gas_price="2")
        validate_and_enqueue_transaction(tx0, node=self.node)

        selected = select_transactions_for_block(self.blockchain, node=self.node)
        proposal = prepare_block_proposal(self.blockchain, selected_entries=selected)
        finalize_block(proposal, selected_entries=selected)

        self.alice_account.refresh_from_db()
        self.assertEqual(self.alice_account.balance, initial_balance - (amount + fee))

        bob_account = Account.objects.get(blockchain=self.blockchain, address=self.bob_address)
        self.assertEqual(bob_account.balance, amount)

    def test_09_sender_nonces_updated_correctly(self):
        """9. Sender nonces are updated correctly upon finalization."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx0, node=self.node)
        selected = select_transactions_for_block(self.blockchain, node=self.node)
        proposal = prepare_block_proposal(self.blockchain, selected_entries=selected)
        finalize_block(proposal, selected_entries=selected)

        self.alice_account.refresh_from_db()
        self.assertEqual(self.alice_account.nonce, 1)

    def test_10_gas_fees_follow_existing_protocol_rules(self):
        """10. Gas fees follow protocol rules and credit proposer validator account."""
        proposer_account = self.validator.account
        initial_proposer_balance = proposer_account.balance

        fee = 21000 * 2
        tx0 = self._sign_tx(amount="1000000000", nonce=0, gas_price="2")
        validate_and_enqueue_transaction(tx0, node=self.node)

        selected = select_transactions_for_block(self.blockchain, node=self.node)
        proposal = prepare_block_proposal(self.blockchain, proposer=self.validator, selected_entries=selected)
        finalize_block(proposal, selected_entries=selected)

        proposer_account.refresh_from_db()
        self.assertEqual(proposer_account.balance, initial_proposer_balance + fee)

    def test_11_receipts_and_events_created_correctly(self):
        """11. Receipts and execution events are created correctly."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        res0 = validate_and_enqueue_transaction(tx0, node=self.node)

        selected = select_transactions_for_block(self.blockchain, node=self.node)
        proposal = prepare_block_proposal(self.blockchain, selected_entries=selected)
        finalized_block = finalize_block(proposal, selected_entries=selected)

        receipt = TransactionReceipt.objects.get(transaction=res0.transaction)
        self.assertEqual(receipt.status, "SUCCESS")
        self.assertEqual(receipt.block_id, finalized_block.id)

        events = TransactionEvent.objects.filter(transaction=res0.transaction)
        self.assertTrue(events.filter(eventType="TRANSFER").exists())
        self.assertTrue(events.filter(eventType="FEE_PAID").exists())

    def test_12_finalized_transactions_removed_from_active_mempool(self):
        """12. Finalized transactions are marked INCLUDED and removed from active mempool."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        res0 = validate_and_enqueue_transaction(tx0, node=self.node)

        produce_next_block(self.blockchain, node=self.node)

        res0.mempool_entry.refresh_from_db()
        self.assertEqual(res0.mempool_entry.status, MempoolStatus.INCLUDED)

        active_count = MempoolTransaction.objects.filter(
            transaction__sender=self.alice_account,
            status=MempoolStatus.ACTIVE,
        ).count()
        self.assertEqual(active_count, 0)

    def test_13_unselected_valid_transactions_remain_in_mempool(self):
        """13. Unselected valid transactions remain active in the mempool for future blocks."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        tx1 = self._sign_tx(amount="1000000000", nonce=1)
        res0 = validate_and_enqueue_transaction(tx0, node=self.node)
        res1 = validate_and_enqueue_transaction(tx1, node=self.node)

        # Batch size 1 selects only nonce 0
        selected = select_transactions_for_block(self.blockchain, node=self.node, batch_size=1)
        self.assertEqual(len(selected), 1)

        proposal = prepare_block_proposal(self.blockchain, selected_entries=selected)
        finalize_block(proposal, selected_entries=selected)

        res0.mempool_entry.refresh_from_db()
        self.assertEqual(res0.mempool_entry.status, MempoolStatus.INCLUDED)

        # Nonce 1 remains active
        res1.mempool_entry.refresh_from_db()
        self.assertEqual(res1.mempool_entry.status, MempoolStatus.ACTIVE)

    def test_14_competing_transactions_become_stale_after_nonce_finalization(self):
        """14. Competing transactions become stale (REPLACED/DROPPED) after nonce finalization."""
        tx0_win = self._sign_tx(amount="1000000000", nonce=0, gas_price="5")
        tx0_competing = self._sign_tx(amount="1500000000", nonce=0, gas_price="2")

        res_win = validate_and_enqueue_transaction(tx0_win, node=self.node)
        # Competing tx with lower fee is retained in permanent storage with mempool status REPLACED
        with self.assertRaises(TransactionValidationError):
            validate_and_enqueue_transaction(tx0_competing, node=self.node)

        competing_tx = Transaction.objects.get(sender=self.alice_account, amount=1500000000)

        # Finalize block with tx0_win
        produce_next_block(self.blockchain, node=self.node)

        competing_tx.refresh_from_db()
        self.assertEqual(competing_tx.status, TransactionStatus.DROPPED)

    def test_15_permanent_transaction_records_retained(self):
        """15. Permanent transaction records are retained without deletion."""
        tx0_win = self._sign_tx(amount="1000000000", nonce=0, gas_price="5")
        tx0_competing = self._sign_tx(amount="1500000000", nonce=0, gas_price="2")

        validate_and_enqueue_transaction(tx0_win, node=self.node)
        with self.assertRaises(TransactionValidationError):
            validate_and_enqueue_transaction(tx0_competing, node=self.node)

        produce_next_block(self.blockchain, node=self.node)

        # Both records must still exist in Transaction table
        stored_txs = Transaction.objects.filter(sender=self.alice_account, nonce=0)
        self.assertEqual(stored_txs.count(), 2)

    def test_16_failed_finalization_rolls_back_database_changes(self):
        """16. A failed finalization rolls back all database changes atomically."""
        initial_balance = self.alice_account.balance
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx0, node=self.node)

        selected = select_transactions_for_block(self.blockchain, node=self.node)
        proposal = prepare_block_proposal(self.blockchain, selected_entries=selected)

        # Create another finalized block ahead of this proposal to simulate race condition
        Block.objects.create(
            blockchain=self.blockchain,
            height=proposal.height,
            parent=proposal.parent,
            proposer=proposal.proposer,
            blockHash=hashlib.sha256(b"block_race").hexdigest(),
            previousHash=proposal.previousHash,
            merkleRoot="0" * 64,
            stateRoot="0" * 64,
            timestamp=timezone.now(),
            status=BlockStatus.FINALIZED,
            finalizedAt=timezone.now(),
        )

        with self.assertRaises(ValueError):
            finalize_block(proposal, selected_entries=selected)

        self.alice_account.refresh_from_db()
        self.assertEqual(self.alice_account.balance, initial_balance)
        self.assertEqual(self.alice_account.nonce, 0)

    def test_17_duplicate_finalization_does_not_apply_financial_changes_twice(self):
        """17. Duplicate finalization is idempotent and does not apply financial changes twice."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx0, node=self.node)

        selected = select_transactions_for_block(self.blockchain, node=self.node)
        proposal = prepare_block_proposal(self.blockchain, selected_entries=selected)
        finalized_block = finalize_block(proposal, selected_entries=selected)

        self.alice_account.refresh_from_db()
        balance_after_first = self.alice_account.balance

        # Call finalize again
        finalize_block(finalized_block, selected_entries=selected)

        self.alice_account.refresh_from_db()
        self.assertEqual(self.alice_account.balance, balance_after_first)
        self.assertEqual(self.alice_account.nonce, 1)

    def test_18_overlapping_block_production_attempts_cannot_finalize_conflicting_blocks(self):
        """18. Two overlapping block production attempts cannot finalize conflicting blocks."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx0, node=self.node)
        selected = select_transactions_for_block(self.blockchain, node=self.node)

        proposal_a = prepare_block_proposal(self.blockchain, selected_entries=selected, round_num=0)
        proposal_b = prepare_block_proposal(self.blockchain, selected_entries=[], round_num=1)

        # Finalize proposal A
        finalize_block(proposal_a, selected_entries=selected)

        # Finalize proposal B must fail because parent is no longer the tip
        with self.assertRaises(ValueError) as ctx:
            finalize_block(proposal_b, selected_entries=[])

        self.assertIn("is no longer latest finalized block", str(ctx.exception))

    def test_19_management_command_calls_production_service_correctly(self):
        """19. The 30-second management command calls the production service correctly."""
        tx0 = self._sign_tx(amount="1000000000", nonce=0)
        validate_and_enqueue_transaction(tx0, node=self.node)

        out = StringIO()
        call_command("run_mempool_processor", single_run=True, stdout=out)
        output = out.getvalue()

        self.assertIn("SUCCESS: Produced Block", output)

        tx_obj = Transaction.objects.get(sender=self.alice_account, nonce=0)
        self.assertEqual(tx_obj.status, TransactionStatus.FINALIZED)

    def test_20_empty_mempool_case_follows_existing_empty_block_policy(self):
        """20. The empty-mempool case follows the existing empty-block policy (returns None)."""
        res = produce_next_block(self.blockchain, node=self.node)
        self.assertIsNone(res)


class BlockListAPITests(TestCase):
    """
    Tests for the BlockListAPIView endpoint:
    - Default pagination of 10 latest blocks (ordered -height)
    - Next/previous page traversal
    - Custom pageSize parameter
    - Query parameter filtering by chainId and status
    """

    def setUp(self):
        from network.services.genesis import GenesisConfig, initialize_blockchain
        from network.services.node_seeder import seed_validator_node

        self.client = APIClient()
        self.config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.gen_res = initialize_blockchain(self.config)
        self.blockchain = self.gen_res.blockchain

        self.seeder_res = seed_validator_node(
            node_id="val-node-blocks-001",
            endpoint="http://localhost:8001",
            node_status="ONLINE",
        )
        self.validator = self.seeder_res.validator

        self.blockchain.refresh_from_db()
        parent = self.blockchain.latestFinalizedBlock
        for h in range(parent.height + 1, 15):
            block = Block.objects.create(
                blockchain=self.blockchain,
                height=h,
                parent=parent,
                proposer=self.validator,
                blockHash=hashlib.sha256(f"block_hash_{h}".encode()).hexdigest(),
                previousHash=parent.blockHash,
                merkleRoot="0" * 64,
                stateRoot="0" * 64,
                timestamp=timezone.now(),
                status=BlockStatus.FINALIZED,
                finalizedAt=timezone.now(),
            )
            parent = block
        self.blockchain.latestFinalizedBlock = parent
        self.blockchain.save(update_fields=["latestFinalizedBlock"])

    def test_list_blocks_default_pagination_latest_10(self):
        """Page 1 returns latest 10 blocks ordered by -height with pagination metadata."""
        response = self.client.get("/api/ledger/blocks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        
        pag_data = response.data["data"]["paginationData"]
        blocks_data = response.data["data"]["blocksData"]
        
        self.assertEqual(pag_data["count"], 15)
        self.assertEqual(pag_data["totalPages"], 2)
        self.assertEqual(pag_data["currentPage"], 1)
        self.assertEqual(pag_data["pageSize"], 10)
        self.assertEqual(len(blocks_data), 10)

        # Check latest ordering (-height: height 14 down to 5)
        self.assertEqual(blocks_data[0]["height"], 14)
        self.assertEqual(blocks_data[9]["height"], 5)
        self.assertIn("page=2", pag_data["next"])
        self.assertIsNone(pag_data["previous"])

        # Check block serializer schema
        first_block = blocks_data[0]
        self.assertIn("blockHash", first_block)
        self.assertIn("parentHash", first_block)
        self.assertIn("merkleRoot", first_block)
        self.assertIn("stateRoot", first_block)
        self.assertEqual(first_block["chainId"], 1001)
        self.assertEqual(first_block["status"], "FINALIZED")

    def test_list_blocks_page_2_traversal(self):
        """Page 2 returns the remaining 5 older blocks (height 4 down to 0)."""
        response = self.client.get("/api/ledger/blocks/?page=2")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        blocks_data = response.data["data"]["blocksData"]
        pag_data = response.data["data"]["paginationData"]
        
        self.assertEqual(len(blocks_data), 5)
        self.assertEqual(blocks_data[0]["height"], 4)
        self.assertEqual(blocks_data[4]["height"], 0)
        self.assertIsNone(pag_data["next"])
        self.assertIsNotNone(pag_data["previous"])

    def test_list_blocks_custom_page_size(self):
        """Passing pageSize=5 yields 5 blocks per page and 3 total pages."""
        response = self.client.get("/api/ledger/blocks/?pageSize=5")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pag_data = response.data["data"]["paginationData"]
        blocks_data = response.data["data"]["blocksData"]
        
        self.assertEqual(pag_data["pageSize"], 5)
        self.assertEqual(pag_data["totalPages"], 3)
        self.assertEqual(len(blocks_data), 5)


class BlockTransactionsAPITests(TestCase):
    """
    Tests for BlockTransactionsAPIView:
    - Return all transactions in a single block using block hash
    - Support both /blocks/<hash>/transactions/ and /blocks/<hash>/
    - Return empty list for block with zero transactions
    - Return 404 for non-existent block hash
    """

    def setUp(self):
        from network.services.genesis import GenesisConfig, initialize_blockchain
        from network.services.node_seeder import seed_validator_node

        self.client = APIClient()
        self.config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.gen_res = initialize_blockchain(self.config)
        self.blockchain = self.gen_res.blockchain
        self.genesis_block = self.gen_res.genesis_block

        self.seeder_res = seed_validator_node(
            node_id="val-node-txs-001",
            endpoint="http://localhost:8001",
            node_status="ONLINE",
        )
        self.validator = self.seeder_res.validator
        self.blockchain.refresh_from_db()

    def test_get_transactions_in_genesis_block(self):
        """Genesis block returns its mint transactions."""
        url = f"/api/ledger/blocks/{self.genesis_block.blockHash}/transactions/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        data = response.data["data"]
        self.assertEqual(data["blockHash"], self.genesis_block.blockHash)
        self.assertEqual(data["blockHeight"], 0)
        self.assertEqual(data["chainId"], 1001)
        self.assertEqual(data["transactionCount"], 3)
        self.assertEqual(len(data["transactions"]), 3)

        # Check transaction fields
        first_tx = data["transactions"][0]
        self.assertIn("txHash", first_tx)
        self.assertEqual(first_tx["txIndex"], 0)
        self.assertIn("senderAddress", first_tx)
        self.assertIn("receiverAddress", first_tx)
        self.assertIn("amount", first_tx)
        self.assertEqual(first_tx["status"], TransactionStatus.FINALIZED)

    def test_get_transactions_via_block_detail_url(self):
        """Block detail URL /api/ledger/blocks/<hash>/ also returns block transactions."""
        url = f"/api/ledger/blocks/{self.genesis_block.blockHash}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["transactionCount"], 3)

    def test_get_transactions_empty_block(self):
        """An empty block with 0 transactions returns an empty list."""
        parent = self.blockchain.latestFinalizedBlock
        empty_block = Block.objects.create(
            blockchain=self.blockchain,
            height=parent.height + 1,
            parent=parent,
            proposer=self.validator,
            blockHash=hashlib.sha256(b"empty_test_block").hexdigest(),
            previousHash=parent.blockHash,
            merkleRoot="0" * 64,
            stateRoot="0" * 64,
            timestamp=timezone.now(),
            status=BlockStatus.FINALIZED,
            transactionCount=0,
            finalizedAt=timezone.now(),
        )

        url = f"/api/ledger/blocks/{empty_block.blockHash}/transactions/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["transactionCount"], 0)
        self.assertEqual(response.data["data"]["transactions"], [])

    def test_get_transactions_non_existent_block_returns_404(self):
        """Querying a non-existent block hash returns 404."""
        non_existent_hash = "0" * 64
        url = f"/api/ledger/blocks/{non_existent_hash}/transactions/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])
        self.assertIn(f"Block with hash '{non_existent_hash}' not found", response.data["reason"])


class TransactionDetailAPITests(TestCase):
    """Integration tests for TransactionDetailAPIView (/api/ledger/transactions/<tx_hash>/)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.genesis_res = initialize_blockchain(self.genesis_config)
        self.blockchain = self.genesis_res.blockchain

        self.seed_res = seed_validator_node(
            node_id="val-tx-detail-001",
            endpoint="http://localhost:8001",
            stake_amount_myc=1000,
            node_status="ONLINE",
        )
        self.node = self.seed_res.node

        # Create sender wallet & account
        self.sender_user = get_user_model().objects.create_user(
            email="sender_detail@test.com",
            firstName="Sender",
            lastName="Detail",
        )
        self.sender_wallet = create_wallet_for_user(self.sender_user)
        self.sender_account = Account.objects.create(
            blockchain=self.blockchain,
            address=self.sender_wallet.address,
            accountType=AccountType.EOA,
            balance=10_000_000_000,
            nonce=0,
            status=AccountStatus.ACTIVE,
        )

        self.tx_hash = "0x" + hashlib.sha256(b"detail_test_tx").hexdigest()
        self.tx = Transaction.objects.create(
            hash=self.tx_hash[2:],
            blockchain=self.blockchain,
            sender=self.sender_account,
            receiverAddress="0x" + "22" * 20,
            txType="TRANSFER",
            amount=1_000_000,
            nonce=0,
            gasLimit=21000,
            gasPrice=1,
            publicKey="04" + "aa" * 64,
            signature="0x" + "bb" * 64,
            status=TransactionStatus.PENDING,
        )

    def test_get_transaction_detail_success(self):
        url = f"/api/ledger/transactions/{self.tx_hash}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        data = response.data["data"]
        self.assertEqual(data["txHash"], self.tx.hash)
        self.assertEqual(data["senderAddress"], self.sender_account.address)
        self.assertEqual(data["receiverAddress"], "0x" + "22" * 20)
        self.assertEqual(data["status"], "PENDING")

    def test_get_transaction_detail_alias_route(self):
        url = f"/api/transactions/{self.tx_hash}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_get_transaction_detail_without_0x_prefix(self):
        url = f"/api/ledger/transactions/{self.tx_hash[2:]}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_get_transaction_detail_not_found(self):
        non_existent = "0x" + "ff" * 32
        url = f"/api/ledger/transactions/{non_existent}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])


class UserTransactionsAPITests(TestCase):
    """Test suite for UserTransactionsAPIView (/api/ledger/transactions/ and /api/wallets/transactions/)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.genesis_res = initialize_blockchain(self.genesis_config)
        self.blockchain = self.genesis_res.blockchain

        self.seed_res = seed_validator_node(
            node_id="val-user-tx-001",
            endpoint="http://localhost:8001",
            stake_amount_myc=1000,
            node_status="ONLINE",
        )
        self.node = self.seed_res.node

        # User A
        self.user_a = get_user_model().objects.create_user(
            email="user_a@test.com",
            firstName="Alice",
            lastName="User",
        )
        self.wallet_a = create_wallet_for_user(self.user_a)
        self.account_a = Account.objects.create(
            blockchain=self.blockchain,
            address=self.wallet_a.address,
            accountType=AccountType.EOA,
            balance=10_000_000_000,
            nonce=0,
            status=AccountStatus.ACTIVE,
        )
        self.token_a = str(RefreshToken.for_user(self.user_a).access_token)

        # User B
        self.user_b = get_user_model().objects.create_user(
            email="user_b@test.com",
            firstName="Bob",
            lastName="User",
        )
        self.wallet_b = create_wallet_for_user(self.user_b)
        self.account_b = Account.objects.create(
            blockchain=self.blockchain,
            address=self.wallet_b.address,
            accountType=AccountType.EOA,
            balance=10_000_000_000,
            nonce=0,
            status=AccountStatus.ACTIVE,
        )
        self.token_b = str(RefreshToken.for_user(self.user_b).access_token)

    def test_unauthenticated_request_returns_401(self):
        url = "/api/ledger/transactions/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_with_no_transactions_returns_empty_list(self):
        new_user = get_user_model().objects.create_user(email="empty@test.com", firstName="No", lastName="Tx")
        token = str(RefreshToken.for_user(new_user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.get("/api/ledger/transactions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["transactionsData"], [])
        self.assertEqual(response.data["data"]["paginationData"]["count"], 0)

    def test_returns_sent_and_received_transactions_with_direction(self):
        # Tx1: User A -> User B
        tx1 = Transaction.objects.create(
            hash=hashlib.sha256(b"tx_a_to_b").hexdigest(),
            blockchain=self.blockchain,
            sender=self.account_a,
            receiverAddress=self.wallet_b.address,
            receiver=self.account_b,
            amount=500_000_000,
            nonce=0,
            gasLimit=21000,
            gasPrice=1,
            publicKey=self.wallet_a.publicKey,
            signature="0x" + "11" * 64,
            status=TransactionStatus.PENDING,
        )

        # Tx2: User B -> User A
        tx2 = Transaction.objects.create(
            hash=hashlib.sha256(b"tx_b_to_a").hexdigest(),
            blockchain=self.blockchain,
            sender=self.account_b,
            receiverAddress=self.wallet_a.address,
            receiver=self.account_a,
            amount=200_000_000,
            nonce=0,
            gasLimit=21000,
            gasPrice=1,
            publicKey=self.wallet_b.publicKey,
            signature="0x" + "22" * 64,
            status=TransactionStatus.PENDING,
        )

        # Request as User A
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")
        response = self.client.get("/api/ledger/transactions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

        data = response.data["data"]
        txs = data["transactionsData"]
        self.assertEqual(len(txs), 2)
        self.assertEqual(data["paginationData"]["count"], 2)

        tx_hashes = [t["txHash"] for t in txs]
        self.assertIn(tx1.hash, tx_hashes)
        self.assertIn(tx2.hash, tx_hashes)

        # Check directions for User A
        direction_map = {t["txHash"]: t["direction"] for t in txs}
        self.assertEqual(direction_map[tx1.hash], "OUTGOING")
        self.assertEqual(direction_map[tx2.hash], "INCOMING")

    def test_pagination_page_and_pagesize(self):
        # Create 15 transactions for User A
        for i in range(15):
            Transaction.objects.create(
                hash=hashlib.sha256(f"pagination_tx_{i}".encode()).hexdigest(),
                blockchain=self.blockchain,
                sender=self.account_a,
                receiverAddress=self.wallet_b.address,
                receiver=self.account_b,
                amount=1_000_000 + i,
                nonce=i,
                gasLimit=21000,
                gasPrice=1,
                publicKey=self.wallet_a.publicKey,
                signature="0x" + "33" * 64,
                status=TransactionStatus.PENDING,
            )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")

        # Page 1 with pageSize=5
        res_page1 = self.client.get("/api/ledger/transactions/?page=1&pageSize=5")
        self.assertEqual(res_page1.status_code, status.HTTP_200_OK)
        data_p1 = res_page1.data["data"]
        self.assertEqual(len(data_p1["transactionsData"]), 5)
        self.assertEqual(data_p1["paginationData"]["count"], 15)
        self.assertEqual(data_p1["paginationData"]["totalPages"], 3)
        self.assertEqual(data_p1["paginationData"]["currentPage"], 1)
        self.assertEqual(data_p1["paginationData"]["pageSize"], 5)
        self.assertIsNotNone(data_p1["paginationData"]["next"])

        # Page 2
        res_page2 = self.client.get("/api/ledger/transactions/?page=2&pageSize=5")
        self.assertEqual(res_page2.status_code, status.HTTP_200_OK)
        data_p2 = res_page2.data["data"]
        self.assertEqual(len(data_p2["transactionsData"]), 5)
        self.assertEqual(data_p2["paginationData"]["currentPage"], 2)

    def test_filter_by_direction(self):
        # Tx outgoing
        Transaction.objects.create(
            hash=hashlib.sha256(b"dir_out").hexdigest(),
            blockchain=self.blockchain,
            sender=self.account_a,
            receiverAddress=self.wallet_b.address,
            amount=100,
            nonce=0,
            gasLimit=21000,
            gasPrice=1,
            publicKey=self.wallet_a.publicKey,
            signature="0x" + "44" * 64,
            status=TransactionStatus.PENDING,
        )
        # Tx incoming
        Transaction.objects.create(
            hash=hashlib.sha256(b"dir_in").hexdigest(),
            blockchain=self.blockchain,
            sender=self.account_b,
            receiverAddress=self.wallet_a.address,
            amount=200,
            nonce=0,
            gasLimit=21000,
            gasPrice=1,
            publicKey=self.wallet_b.publicKey,
            signature="0x" + "55" * 64,
            status=TransactionStatus.PENDING,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")

        # Filter sent
        res_sent = self.client.get("/api/ledger/transactions/?direction=sent")
        self.assertEqual(res_sent.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_sent.data["data"]["transactionsData"]), 1)
        self.assertEqual(res_sent.data["data"]["transactionsData"][0]["direction"], "OUTGOING")

        # Filter received
        res_rec = self.client.get("/api/ledger/transactions/?direction=received")
        self.assertEqual(res_rec.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_rec.data["data"]["transactionsData"]), 1)
        self.assertEqual(res_rec.data["data"]["transactionsData"][0]["direction"], "INCOMING")

    def test_accessible_via_wallet_and_alias_routes(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")
        res_wallet = self.client.get("/api/wallets/transactions/")
        self.assertEqual(res_wallet.status_code, status.HTTP_200_OK)
        self.assertTrue(res_wallet.data["success"])

        res_alias = self.client.get("/api/transactions/")
        self.assertEqual(res_alias.status_code, status.HTTP_200_OK)
        self.assertTrue(res_alias.data["success"])




