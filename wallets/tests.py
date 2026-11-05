"""
Tests for Wallet creation, key generation, and registration flow integration.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
import ecdsa

from accounts.application.confirm_register_otp import ConfirmRegisterOtpUseCase
from accounts.infrastructure.activity import DjangoActivityRecorder
from accounts.infrastructure.jwt_adapter import DjangoJWTAdapter
from accounts.infrastructure.otp_repository import DjangoOTPRepository
from accounts.infrastructure.user_repository import DjangoUserRepository
from accounts.infrastructure.wallet_adapter import DjangoWalletAdapter
from accounts.models import UserOTP
from wallets.models import Account, Wallet, WalletStatus, WalletType
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
