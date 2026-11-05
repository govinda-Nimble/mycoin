from typing import Optional
from django.utils import timezone
from accounts.domain import (
    ActivityRecorder,
    OTPManager,
    TokenManager,
    UseCaseResult,
    UserReader,
    UserWriter,
)


class LoginOtpVerificationUseCase:
    """
    Orchestrates login OTP validation, updates user last login,
    and returns JWT credentials upon successful verification.
    """

    def __init__(
        self,
        user_reader: UserReader,
        user_writer: UserWriter,
        otp_manager: OTPManager,
        token_manager: TokenManager,
        activity_recorder: ActivityRecorder,
    ):
        self._users = user_reader
        self._user_writer = user_writer
        self._otps = otp_manager
        self._tokens = token_manager
        self._activity = activity_recorder

    def execute(
        self,
        *,
        email: str,
        otp: str,
        client_ip: Optional[str] = None,
    ) -> UseCaseResult:
        clean_email = email.strip().lower()

        # 1. Check user exists
        user = self._users.find_active_by_email(clean_email)
        if not user:
            return UseCaseResult(
                success=False,
                reason="Account not found. Please sign up first.",
                status_code=404,
            )

        if not getattr(user, "is_active", True):
            return UseCaseResult(
                success=False,
                reason="Your account is inactive. Please contact support.",
                status_code=403,
            )

        # 2. Fetch login OTP record
        otp_record = self._otps.find_latest_login_otp(email=clean_email)
        if not otp_record:
            return UseCaseResult(
                success=False,
                reason="No active login OTP found for this email. Please request an OTP first.",
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

        # 4. Mark OTP verified
        self._otps.mark_otp_verified(otp_record=otp_record, user=user)

        # 5. Update last login
        self._user_writer.update_last_login(user)

        # 6. Issue JWT tokens
        tokens = self._tokens.create_token_pair_for_user(user)

        # 7. Record activity
        self._activity.record_login(user=user, ip_address=client_ip)

        return UseCaseResult(
            success=True,
            reason="Login successful.",
            status_code=200,
            data={
                "tokens": tokens,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "firstName": getattr(user, "firstName", ""),
                    "lastName": getattr(user, "lastName", ""),
                    "isEmailVerified": getattr(user, "isEmailVerified", True),
                },
            },
        )

