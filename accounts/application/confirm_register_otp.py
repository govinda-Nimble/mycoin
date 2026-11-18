from typing import Optional
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.utils import timezone
from accounts.domain import (
    ActivityRecorder,
    OTPManager,
    TokenManager,
    UseCaseResult,
    UserReader,
    UserWriter,
    WalletCreator,
)
from common.utils import format_database_constraint_error


class ConfirmRegisterOtpUseCase:
    """
    Orchestrates OTP verification, creates the User model,
    automatically provisions a secure keystore Wallet,
    links the OTP record to the created user, and generates auth tokens.
    """

    def __init__(
        self,
        user_reader: UserReader,
        user_writer: UserWriter,
        otp_manager: OTPManager,
        token_manager: TokenManager,
        activity_recorder: ActivityRecorder,
        wallet_creator: Optional[WalletCreator] = None,
    ):
        self._users = user_reader
        self._user_writer = user_writer
        self._otps = otp_manager
        self._tokens = token_manager
        self._activity = activity_recorder
        self._wallet_creator = wallet_creator

    def execute(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        otp: str,
        client_ip: Optional[str] = None,
    ) -> UseCaseResult:
        clean_email = email.strip().lower()

        # 1. Prevent duplicate user creation
        if self._users.exists_by_email(clean_email):
            return UseCaseResult(
                success=False,
                reason="This email is already registered. Please log in.",
                status_code=400,
            )

        # 2. Fetch OTP record
        otp_record = self._otps.find_latest_registration_otp(email=clean_email)
        if not otp_record:
            return UseCaseResult(
                success=False,
                reason="No active OTP request found for this email. Please request an OTP first.",
                status_code=400,
            )

        if getattr(otp_record, "isVerified", False):
            return UseCaseResult(
                success=False,
                reason="This OTP has already been verified.",
                status_code=400,
            )

        if timezone.now() > getattr(otp_record, "expiresAt"):
            return UseCaseResult(
                success=False,
                reason="OTP has expired. Please request a new OTP.",
                status_code=400,
            )

        if getattr(otp_record, "attempts", 0) >= getattr(otp_record, "maxAttempts", 5):
            return UseCaseResult(
                success=False,
                reason="Maximum verification attempts exceeded. Please request a new OTP.",
                status_code=400,
            )

        # 3. Match raw OTP
        if getattr(otp_record, "otp") != otp.strip():
            self._otps.increment_attempts(otp_record=otp_record)
            return UseCaseResult(
                success=False,
                reason="Invalid OTP. Please check and try again.",
                status_code=400,
            )

        # 4. Create user record
        try:
            user = self._user_writer.create_user(
                email=clean_email,
                firstName=first_name,
                lastName=last_name,
                is_email_verified=True,
            )
        except (IntegrityError, DjangoValidationError) as err:
            clean_err = format_database_constraint_error(err)
            return UseCaseResult(
                success=False,
                reason=clean_err,
                status_code=400,
            )

        # 5. Provision Wallet & On-Chain Account with Registration Bonus
        wallet = None
        account = None
        if self._wallet_creator:
            wallet = self._wallet_creator.create_wallet_for_user(user)
            if wallet and hasattr(self._wallet_creator, "create_account_for_wallet"):
                try:
                    account = self._wallet_creator.create_account_for_wallet(user=user, wallet=wallet)
                except Exception:
                    account = None

        # 6. Link OTP record to the created user and mark verified
        self._otps.mark_otp_verified(otp_record=otp_record, user=user)

        # 7. Issue JWT tokens for seamless onboarding
        tokens = self._tokens.create_token_pair_for_user(user)

        # 8. Record activity
        self._activity.record_registration_completed(user=user, ip_address=client_ip)

        response_data = {
            "tokenData": tokens,
            "userData": {
                "id": str(user.id),
                "email": user.email,
                "firstName": getattr(user, "firstName", ""),
                "lastName": getattr(user, "lastName", ""),
                "userType": getattr(user, "userType", "INDIVIDUAL"),
            },
        }

        if wallet:
            response_data["walletData"] = {
                "id": str(wallet.id),
                "address": wallet.address,
                "publicKey": wallet.publicKey,
            }

        if account:
            response_data["accountData"] = {
                "id": str(account.id),
                "address": account.address,
                "balance": str(account.balance),
                "bonusAmount": "100 MYC",
                "accountType": account.accountType,
                "status": account.status,
            }

        return UseCaseResult(
            success=True,
            reason="Account created successfully.",
            status_code=201,
            data=response_data,
        )
