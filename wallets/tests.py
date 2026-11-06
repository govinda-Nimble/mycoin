"""
Tests for Wallet creation, key generation, registration flow integration,
and transaction signing API (using camelCase convention).
"""

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
from network.models import Blockchain, BlockchainStatus
from wallets.models import Account, Wallet, WalletStatus, WalletType
from wallets.services.transaction_signer import (
    serialize_transaction_for_signing,
    sign_transaction_for_user,
    sign_transaction_payload,
)
from wallets.services.wallet_service import create_wallet_for_user, generate_keypair

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
            hashfunc=ecdsa.util.hashlib.sha256,
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
