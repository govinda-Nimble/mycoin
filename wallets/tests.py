"""
Tests for Wallet creation, key generation, registration flow integration,
and transaction signing API (using camelCase convention).
"""

from datetime import timedelta
from decimal import Decimal
import hashlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
import ecdsa
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.application.confirm_register_otp import ConfirmRegisterOtpUseCase
from accounts.infrastructure.activity import DjangoActivityRecorder
from accounts.infrastructure.jwt_adapter import DjangoJWTAdapter
from accounts.infrastructure.otp_repository import DjangoOTPRepository
from accounts.infrastructure.user_repository import DjangoUserRepository
from accounts.infrastructure.wallet_adapter import DjangoWalletAdapter
from ledger.models import MempoolStatus, MempoolTransaction, Transaction, TransactionStatus
from network.models import Blockchain, BlockchainStatus, Node
from wallets.models import Account, Wallet, WalletStatus, WalletType
from wallets.services.transaction_signer import (
    serialize_transaction_for_signing,
    sign_transaction_for_user,
    sign_transaction_payload,
)
from wallets.services.wallet_service import (
    create_wallet_for_user,
    format_coin_amount,
    generate_keypair,
    get_account_balance,
)

User = get_user_model()


class WalletServiceTests(TestCase):
    """Unit tests for the wallet generation service."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            email="crypto_user@example.com",
            firstName="Satoshi",
            lastName="Nakamoto",
            userType="INDIVIDUAL",
        )

    def test_generate_keypair(self):
        """Test cryptographic keypair generation conforms to SECP256k1 standards."""
        private_key, public_key, address = generate_keypair()

        self.assertEqual(len(private_key), 64)
        self.assertEqual(len(public_key), 130)
        self.assertTrue(public_key.startswith("04"))
        self.assertEqual(len(address), 42)
        self.assertTrue(address.startswith("0x"))

        # Verify SigningKey can be reconstructed and signs correctly
        sk = ecdsa.SigningKey.from_string(bytes.fromhex(private_key), curve=ecdsa.SECP256k1)
        vk = sk.get_verifying_key()
        self.assertEqual(vk.to_string().hex(), public_key[2:])

        message = b"Test signature for prototype transaction"
        signature = sk.sign(message)
        self.assertTrue(vk.verify(signature, message))

    def test_create_wallet_for_user(self):
        """Test creating an active keystore wallet for a registered user."""
        wallet = create_wallet_for_user(self.user)

        self.assertIsNotNone(wallet.id)
        self.assertEqual(wallet.user, self.user)
        self.assertEqual(wallet.walletType, WalletType.KEYSTORE)
        self.assertEqual(wallet.status, WalletStatus.ACTIVE)
        self.assertEqual(len(wallet.address), 42)
        self.assertTrue(wallet.address.startswith("0x"))
        self.assertEqual(len(wallet.publicKey), 130)

        # Verify privateKey access and signing capability
        self.assertEqual(wallet.privateKey, wallet.keyReference)
        self.assertEqual(len(wallet.privateKey), 64)

        signing_key = wallet.get_signing_key()
        self.assertIsInstance(signing_key, ecdsa.SigningKey)
        sig = signing_key.sign(b"MYC transfer signature")
        self.assertTrue(signing_key.get_verifying_key().verify(sig, b"MYC transfer signature"))

    def test_create_wallet_idempotency(self):
        """Test calling wallet creation again returns the existing active wallet."""
        wallet1 = create_wallet_for_user(self.user)
        wallet2 = create_wallet_for_user(self.user)

        self.assertEqual(wallet1.id, wallet2.id)
        self.assertEqual(wallet1.address, wallet2.address)
        self.assertEqual(Wallet.objects.filter(user=self.user).count(), 1)


class RegistrationWalletIntegrationTests(TestCase):
    """Integration test verifying wallet creation during the user registration OTP flow."""

    def setUp(self):
        super().setUp()
        self.user_repo = DjangoUserRepository()
        self.otp_repo = DjangoOTPRepository()
        self.jwt_adapter = DjangoJWTAdapter()
        self.activity_recorder = DjangoActivityRecorder()
        self.wallet_adapter = DjangoWalletAdapter()

        self.use_case = ConfirmRegisterOtpUseCase(
            user_reader=self.user_repo,
            user_writer=self.user_repo,
            otp_manager=self.otp_repo,
            token_manager=self.jwt_adapter,
            activity_recorder=self.activity_recorder,
            wallet_creator=self.wallet_adapter,
        )

    def test_registration_creates_user_and_wallet_without_account(self):
        """Verify registration flow creates User + Wallet, stores private key, and defers Account creation."""
        email = "alice@example.com"
        raw_otp = "111111"

        # Create active registration OTP
        self.otp_repo.upsert_registration_otp(
            email=email,
            otp=raw_otp,
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )

        # Execute OTP confirmation
        result = self.use_case.execute(
            first_name="Alice",
            last_name="Crypto",
            email=email,
            otp=raw_otp,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status_code, 201)

        # Verify user record
        user = User.objects.get(email=email)
        self.assertEqual(user.firstName, "Alice")
        self.assertEqual(user.lastName, "Crypto")
        self.assertEqual(user.userType, "INDIVIDUAL")
        self.assertTrue(user.isEmailVerified)

        # Verify wallet was created automatically
        wallet = Wallet.objects.get(user=user)
        self.assertEqual(wallet.walletType, WalletType.KEYSTORE)
        self.assertEqual(wallet.status, WalletStatus.ACTIVE)
        self.assertEqual(len(wallet.address), 42)
        self.assertTrue(wallet.address.startswith("0x"))

        # Verify private key is stored for prototype backend signing
        self.assertEqual(len(wallet.privateKey), 64)
        self.assertEqual(wallet.privateKey, wallet.keyReference)

        # Verify NO Account model was created yet (deferred to first MYC transfer)
        self.assertEqual(Account.objects.filter(wallet=wallet).count(), 0)

        # Verify walletData is included in the use case result
        self.assertIn("walletData", result.data)
        self.assertEqual(result.data["walletData"]["address"], wallet.address)
        self.assertEqual(result.data["walletData"]["publicKey"], wallet.publicKey)

    def test_registration_with_active_blockchain_creates_account_and_registration_bonus(self):
        """Verify registration with active blockchain provisions Account, transfers 100 MYC bonus, and finalizes Block."""
        from ledger.models import Block, Transaction, TransactionType
        from network.services.genesis import GenesisConfig, TREASURY_ADDRESS, initialize_blockchain

        # 1. Initialize active blockchain
        genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        genesis_res = initialize_blockchain(genesis_config)
        blockchain = genesis_res.blockchain

        treasury = Account.objects.get(blockchain=blockchain, address=TREASURY_ADDRESS)
        initial_treasury_balance = treasury.balance

        email = "bob_bonus@example.com"
        raw_otp = "222222"

        self.otp_repo.upsert_registration_otp(
            email=email,
            otp=raw_otp,
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )

        result = self.use_case.execute(
            first_name="Bob",
            last_name="Bonus",
            email=email,
            otp=raw_otp,
        )

        self.assertTrue(result.success)
        self.assertIn("accountData", result.data)
        self.assertEqual(result.data["accountData"]["bonusAmount"], "100 MYC")

        user = User.objects.get(email=email)
        wallet = Wallet.objects.get(user=user)
        account = Account.objects.get(wallet=wallet, blockchain=blockchain)

        # 100 MYC in 8 decimals = 10,000,000,000 base units
        expected_bonus_units = 100 * (10 ** blockchain.decimals)
        self.assertEqual(account.balance, expected_bonus_units)
        self.assertEqual(account.address, wallet.address)

        # Verify Treasury debited
        treasury.refresh_from_db()
        self.assertEqual(treasury.balance, initial_treasury_balance - expected_bonus_units)

        # Verify Registration Block created and finalized
        blockchain.refresh_from_db()
        tip_block = blockchain.latestFinalizedBlock
        self.assertIsNotNone(tip_block)
        self.assertEqual(tip_block.status, "FINALIZED")
        self.assertEqual(account.creationBlock, tip_block)

        # Verify Registration Bonus transaction
        reg_tx = Transaction.objects.filter(
            blockchain=blockchain,
            receiver=account,
            txType=TransactionType.REG_BONUS,
        ).first()
        self.assertIsNotNone(reg_tx)
        self.assertEqual(reg_tx.amount, expected_bonus_units)
        self.assertEqual(reg_tx.status, "FINALIZED")
        self.assertEqual(reg_tx.block, tip_block)

        # Create receiver on-chain account for transfer validation
        receiver_addr = "0x" + "9" * 40
        Account.objects.create(
            blockchain=blockchain,
            address=receiver_addr,
            accountType="EOA",
            balance=0,
            nonce=0,
            status="ACTIVE",
        )

        # Verify Bob can now sign and validate a transfer of 20 MYC
        signed_tx = sign_transaction_for_user(
            user=user,
            receiver_address=receiver_addr,
            amount="2000000000",
        )
        self.assertEqual(signed_tx["senderAddress"], account.address)
        self.assertEqual(signed_tx["nonce"], 0)

        # Submit to Check Transaction API
        client = APIClient()
        check_res = client.post("/api/ledger/transactions/check/", signed_tx, format="json")
        self.assertEqual(check_res.status_code, 201)
        self.assertTrue(check_res.json()["success"])
        self.assertEqual(check_res.json()["data"]["status"], "PENDING")


class SignTransactionAPITests(TestCase):
    """API tests for the /api/wallets/sign-transaction/ endpoint using camelCase."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Seed blockchain
        self.blockchain = Blockchain.objects.create(
            name="MYCOIN",
            symbol="MYC",
            chainId=1001,
            decimals=8,
            baseTransferGas=21000,
            minGasPrice=1,
            status=BlockchainStatus.ACTIVE,
        )

        # Create user & active wallet
        self.user = User.objects.create_user(
            email="signer@example.com",
            firstName="Alice",
            lastName="Signer",
            userType="INDIVIDUAL",
        )
        self.wallet = create_wallet_for_user(self.user)

        # Generate JWT token
        refresh = RefreshToken.for_user(self.user)
        self.access_token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

        self.sign_url = reverse("sign-transaction")
        self.receiver_address = "0x0000000000000000000000000000000000000002"

    def test_sign_transaction_success_camelcase(self):
        """Test user sends only amount and receiverAddress; backend resolves all other fields in camelCase."""
        payload = {
            "amount": "1000000000",
            "receiverAddress": self.receiver_address,
        }

        response = self.client.post(self.sign_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        # Verify camelCase field names and correct values
        self.assertEqual(data["senderAddress"], self.wallet.address)
        self.assertEqual(data["receiverAddress"], self.receiver_address)
        self.assertEqual(data["amount"], "1000000000")
        self.assertEqual(data["nonce"], 0)
        self.assertEqual(data["gasLimit"], 21000)
        self.assertEqual(data["gasPrice"], "2")
        self.assertEqual(data["publicKey"], self.wallet.publicKey)
        self.assertTrue(data["signature"].startswith("0x"))
        self.assertEqual(len(data["signature"]), 130)  # 0x + 128 hex chars (64 bytes r+s)

        # Cryptographically verify the signature
        vk = self.wallet.get_signing_key().get_verifying_key()
        digest = serialize_transaction_for_signing(
            chain_id=1001,
            sender_address=self.wallet.address,
            receiver_address=self.receiver_address,
            amount="1000000000",
            nonce=0,
            gas_limit=21000,
            gas_price="2",
        )
        sig_raw = bytes.fromhex(data["signature"][2:])
        verified = vk.verify(
            sig_raw,
            digest,
            hashfunc=hashlib.sha256,
            sigdecode=ecdsa.util.sigdecode_string,
        )
        self.assertTrue(verified)

    def test_sign_transaction_unauthenticated_fails(self):
        """Test unauthenticated request returns 401 Unauthorized."""
        self.client.credentials()  # Remove credentials
        payload = {
            "amount": "1000000000",
            "receiverAddress": self.receiver_address,
        }
        response = self.client.post(self.sign_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_sign_transaction_no_wallet_fails(self):
        """Test user without an active wallet returns 400 Bad Request."""
        user_no_wallet = User.objects.create_user(
            email="nowallet@example.com",
            firstName="No",
            lastName="Wallet",
            userType="INDIVIDUAL",
        )
        refresh = RefreshToken.for_user(user_no_wallet)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        payload = {
            "amount": "1000000000",
            "receiverAddress": self.receiver_address,
        }
        response = self.client.post(self.sign_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("User does not have an active wallet", response.data["error"])

    def test_sign_transaction_invalid_receiver_address(self):
        """Test invalid receiver address returns 400 Bad Request."""
        payload = {
            "amount": "1000000000",
            "receiverAddress": "invalid-address-format",
        }
        response = self.client.post(self.sign_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("receiveraddress", response.data["error"].lower())

    def test_sign_transaction_invalid_amount(self):
        """Test negative or zero amount returns 400 Bad Request."""
        payload = {
            "amount": "0",
            "receiverAddress": self.receiver_address,
        }
        response = self.client.post(self.sign_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("greater than zero", response.data["error"])

    def test_sign_transaction_uses_onchain_account_nonce(self):
        """Test that if on-chain Account exists, its nonce is automatically picked up."""
        Account.objects.create(
            blockchain=self.blockchain,
            wallet=self.wallet,
            address=self.wallet.address,
            balance=10_000_000_000,
            nonce=7,
        )

        payload = {
            "amount": "1000000000",
            "receiverAddress": self.receiver_address,
        }
        response = self.client.post(self.sign_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["nonce"], 7)


class CheckBalanceAPITests(TestCase):
    """
    Unit and integration tests for the Check User Balance API.
    Verifies camelCase response keys, finalized vs available balance with mempool deductions,
    address lookup, and authentication requirements.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Seed blockchain
        self.blockchain = Blockchain.objects.create(
            name="MYCOIN DevNet",
            symbol="MYC",
            chainId=1001,
            decimals=8,
            baseTransferGas=21000,
            minGasPrice=1,
            status=BlockchainStatus.ACTIVE,
        )

        # Create user & active wallet
        self.user = User.objects.create_user(
            email="balance_user@example.com",
            firstName="Bob",
            lastName="Hodler",
            userType="INDIVIDUAL",
        )
        self.wallet = create_wallet_for_user(self.user, name="Bob's Primary Wallet")

        # Create on-chain Account with 100 MYC (10,000,000,000 units)
        self.account = Account.objects.create(
            blockchain=self.blockchain,
            wallet=self.wallet,
            address=self.wallet.address,
            balance=10_000_000_000,
            nonce=2,
            status="ACTIVE",
        )

        # Authenticate user
        refresh = RefreshToken.for_user(self.user)
        self.access_token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

        self.balance_url = reverse("wallet-balance")

    def test_check_balance_authenticated_user_success(self):
        """Test authenticated user retrieving their own balance without passing query params."""
        response = self.client.get(self.balance_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        # Verify camelCase keys and correct values
        self.assertEqual(data["address"], self.wallet.address)
        self.assertEqual(data["balance"], 10_000_000_000)
        self.assertEqual(data["balanceFormatted"], "100.00000000")
        self.assertEqual(data["availableBalance"], 10_000_000_000)
        self.assertEqual(data["availableBalanceFormatted"], "100.00000000")
        self.assertEqual(data["pendingTransactionsCount"], 0)
        self.assertEqual(data["symbol"], "MYC")
        self.assertEqual(data["decimals"], 8)
        self.assertEqual(data["nonce"], 2)
        self.assertEqual(data["chainId"], 1001)
        self.assertEqual(data["networkName"], "MYCOIN DevNet")
        self.assertEqual(data["status"], "ACTIVE")

    def test_check_balance_by_address_query_param(self):
        """Test retrieving balance for a specific target address via query parameter."""
        target_address = "0x0000000000000000000000000000000000000099"
        Account.objects.create(
            blockchain=self.blockchain,
            address=target_address,
            balance=5_000_000_000,
            nonce=1,
            status="ACTIVE",
        )

        response = self.client.get(f"{self.balance_url}?address={target_address}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["address"], target_address)
        self.assertEqual(response.data["balance"], 5_000_000_000)
        self.assertEqual(response.data["balanceFormatted"], "50.00000000")

    def test_check_balance_by_path_param(self):
        """Test retrieving balance for a specific target address via path parameter."""
        target_address = "0x0000000000000000000000000000000000000088"
        Account.objects.create(
            blockchain=self.blockchain,
            address=target_address,
            balance=2_500_000_000,
            nonce=0,
            status="ACTIVE",
        )

        response = self.client.get(f"/api/wallets/balance/{target_address}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["address"], target_address)
        self.assertEqual(response.data["balance"], 2_500_000_000)
        self.assertEqual(response.data["balanceFormatted"], "25.00000000")

    def test_check_balance_unauthenticated_without_address_fails_401(self):
        """Test unauthenticated request without address parameter returns 401 Unauthorized."""
        self.client.credentials()  # Clear auth headers
        response = self.client.get(self.balance_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Authentication credentials were not provided", response.data["reason"])

    def test_check_balance_unauthenticated_with_address_succeeds_200(self):
        """Test unauthenticated request with target address parameter succeeds (public blockchain query)."""
        self.client.credentials()  # Clear auth headers
        response = self.client.get(f"{self.balance_url}?address={self.wallet.address}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["address"], self.wallet.address)
        self.assertEqual(response.data["balance"], 10_000_000_000)

    def test_check_balance_invalid_address_format_fails_400(self):
        """Test invalid address format returns 400 Bad Request."""
        response = self.client.get(f"{self.balance_url}?address=not-a-valid-0x-address")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Must be '0x' followed by 40 hexadecimal characters", response.data["reason"])

    def test_check_balance_unregistered_address_returns_zero(self):
        """Test query for an address that has never transacted on-chain returns zero balance cleanly."""
        unused_address = "0x1111111111111111111111111111111111111111"
        response = self.client.get(f"{self.balance_url}?address={unused_address}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["address"], unused_address)
        self.assertEqual(response.data["balance"], 0)
        self.assertEqual(response.data["balanceFormatted"], "0.00000000")
        self.assertEqual(response.data["nonce"], 0)

    def test_check_balance_with_pending_mempool_deduction(self):
        """Test that active pending mempool transactions reduce availableBalance."""
        node = Node.objects.create(
            blockchain=self.blockchain,
            nodeId="val-test-01",
            endpoint="http://localhost:8001",
        )

        # Create pending transaction for 20 MYC (2,000,000,000) + gas fee (21000 * 2 = 42000)
        tx_hash = hashlib.sha256(b"pending_tx_hash").hexdigest()
        tx = Transaction.objects.create(
            hash=tx_hash,
            blockchain=self.blockchain,
            sender=self.account,
            receiverAddress="0x0000000000000000000000000000000000000002",
            amount=2_000_000_000,
            nonce=2,
            gasLimit=21000,
            gasPrice=2,
            status=TransactionStatus.PENDING,
            signature="a" * 128,
            publicKey="04" + "b" * 126,
        )
        now = timezone.now()
        MempoolTransaction.objects.create(
            transaction=tx,
            node=node,
            priority=2,
            arrivalTime=now,
            expiresAt=now + timedelta(hours=1),
            status=MempoolStatus.ACTIVE,
        )

        response = self.client.get(self.balance_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        # Finalized balance remains 100 MYC
        self.assertEqual(data["balance"], 10_000_000_000)
        self.assertEqual(data["balanceFormatted"], "100.00000000")

        # Available balance accounts for 20 MYC + 42,000 gas fee deduction
        expected_deduction = 2_000_000_000 + (21000 * 2)
        expected_available = 10_000_000_000 - expected_deduction
        self.assertEqual(data["availableBalance"], expected_available)
        self.assertEqual(data["availableBalanceFormatted"], format_coin_amount(expected_available, 8))
        self.assertEqual(data["pendingTransactionsCount"], 1)

