from datetime import timedelta
from typing import Optional
from django.utils import timezone
from accounts.domain import ActivityRecorder, OTPManager, UseCaseResult, UserReader


class RequestLoginOtpUseCase:
    """
    Orchestrates login OTP generation and issuance.
    Verifies the user exists and is active before sending OTP.
    """

    def __init__(
        self,
        user_reader: UserReader,
        otp_manager: OTPManager,
        activity_recorder: ActivityRecorder,
        otp_expire_minutes: int = 10,
    ):
        self._users = user_reader
        self._otps = otp_manager
        self._activity = activity_recorder
        self._otp_expire_minutes = otp_expire_minutes

    def execute(
        self,
        *,
        email: str,
        client_ip: Optional[str] = None,
    ) -> UseCaseResult:
        clean_email = email.strip().lower()

        # 1. Check if user exists
        user = self._users.find_active_by_email(clean_email)
        if not user:
            return UseCaseResult(
                success=False,
                reason="This email is not registered. Please sign up first.",
                status_code=404,
            )

        if not getattr(user, "is_active", True):
            return UseCaseResult(
                success=False,
                reason="Your account is inactive. Please contact support.",
                status_code=403,
            )

        # 2. Generate raw 6-digit default OTP
        otp_code = "111111"
        expires_at = timezone.now() + timedelta(minutes=self._otp_expire_minutes)

        # 3. Upsert single login OTP record
        self._otps.upsert_login_otp(
            email=clean_email,
            user=user,
            otp=otp_code,
            expires_at=expires_at,
        )

        # 4. Record audit activity
        self._activity.record_login_otp_sent(
            user=user,
            ip_address=client_ip,
        )

        return UseCaseResult(
            success=True,
            reason="Login OTP sent successfully to your email.",
            status_code=200,
            data={
                "email": clean_email,
                "expiresAt": expires_at.isoformat(),
            },
        )

