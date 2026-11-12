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
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from ledger.management.commands.run_mempool_processor import Command as MempoolProcessorCommand
from ledger.models import MempoolStatus, MempoolTransaction, Transaction, TransactionStatus
from ledger.services.mempool_processor import (
    DEFAULT_BATCH_SIZE,
    MempoolProcessingResult,
    process_mempool,
    try_acquire_advisory_lock,
)
from network.models import Blockchain, BlockchainStatus
from network.services.genesis import GenesisConfig, initialize_blockchain
from network.services.node_seeder import seed_validator_node
from wallets.models import Account, AccountStatus, AccountType, Wallet, WalletStatus
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
            wallet=self.alice_wallet,
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

        response = self.client.post("/api/ledger/transactions/check/", payload, format="json")
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

        response = self.client.post("/api/ledger/transactions/check/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_SENDER")

    def test_check_receiver_identical_to_sender(self):
        """Check 2: Self-transfer is rejected."""
        payload = self._sign_tx(receiver_address=self.alice_wallet.address)

        response = self.client.post("/api/ledger/transactions/check/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_RECEIVER")

    def test_verify_public_key_mismatch(self):
        """Check 3: Public key not deriving sender address is rejected."""
        payload = self._sign_tx()
        # Tamper public key with Bob's public key
        payload["publicKey"] = self.bob_wallet.publicKey

        response = self.client.post("/api/ledger/transactions/check/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "VERIFY_PUBLIC_KEY")

    def test_verify_signature_tampered(self):
        """Check 4: Tampered amount or invalid signature is rejected."""
        payload = self._sign_tx(amount="2000000000")
        # Tamper amount after signing
        payload["amount"] = "9999999999"

        response = self.client.post("/api/ledger/transactions/check/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "VERIFY_SIGNATURE")

    def test_check_nonce_too_low(self):
        """Check 5: Nonce lower than account nonce is rejected."""
        self.alice_account.nonce = 5
        self.alice_account.save()

        payload = self._sign_tx(nonce=2)

        response = self.client.post("/api/ledger/transactions/check/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_NONCE")
        self.assertIn("Nonce too low", response.json()["reason"])

    def test_check_nonce_conflict_live_tx(self):
        """Check 5: Duplicate nonce on live transaction is rejected."""
        payload1 = self._sign_tx(nonce=0)
        res1 = self.client.post("/api/ledger/transactions/check/", payload1, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Another transaction with different amount but same nonce 0
        payload2 = self._sign_tx(amount="3000000000", nonce=0)
        res2 = self.client.post("/api/ledger/transactions/check/", payload2, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res2.json()["step"], "CHECK_NONCE")
        self.assertIn("Nonce conflict", res2.json()["reason"])

    def test_check_balance_insufficient(self):
        """Check 6: Insufficient balance is rejected."""
        # Alice only has 1,000 MYC (100,000,000,000 units), try to send 2,000 MYC
        payload = self._sign_tx(amount="200000000000")

        response = self.client.post("/api/ledger/transactions/check/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_BALANCE")
        self.assertIn("Insufficient balance", response.json()["reason"])

    def test_check_gas_limit_below_base(self):
        """Check 7: Gas limit below baseTransferGas is rejected."""
        # baseTransferGas is 21000
        payload = self._sign_tx(gas_limit=10000)

        response = self.client.post("/api/ledger/transactions/check/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["step"], "CHECK_GAS")
        self.assertIn("below minimum base transfer gas", response.json()["reason"])

    def test_check_duplicate_hash(self):
        """Check 8: Submitting identical transaction payload twice is rejected."""
        payload = self._sign_tx(nonce=0)

        res1 = self.client.post("/api/ledger/transactions/check/", payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Submit identical payload again
        res2 = self.client.post("/api/ledger/transactions/check/", payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        # It gets caught as nonce conflict or duplicate hash
        self.assertIn(res2.json()["step"], ["CHECK_NONCE", "CHECK_DUPLICATE_HASH"])

    def test_endpoint_aliases(self):
        """Verify API is accessible via all configured alias endpoints."""
        endpoints = [
            "/api/ledger/transactions/check/",
            "/api/ledger/transactions/validate/",
            "/api/transactions/check/",
            "/api/wallets/transactions/check/",
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
            wallet=self.alice_wallet,
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
            wallet=self.alice_wallet,
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
                wallet=w,
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
