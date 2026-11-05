from datetime import timedelta
from typing import Optional
from django.utils import timezone
from accounts.domain import ActivityRecorder, OTPManager, UseCaseResult, UserReader


class RegisterAccountUseCase:
    """
    Orchestrates initial registration request by validating email uniqueness
    and issuing a registration OTP.
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
        first_name: str,
        last_name: str,
        email: str,
        client_ip: Optional[str] = None,
    ) -> UseCaseResult:
        clean_email = email.strip().lower()

        # 1. Verify email uniqueness
        if self._users.exists_by_email(clean_email):
            return UseCaseResult(
                success=False,
                reason="A user with this email already exists.",
                status_code=400,
            )

        # 2. Generate raw 6-digit default OTP
        otp_code = "111111"
        expires_at = timezone.now() + timedelta(minutes=self._otp_expire_minutes)

        # 3. Upsert single OTP record using get_or_create
        self._otps.upsert_registration_otp(
            email=clean_email,
            otp=otp_code,
            expires_at=expires_at,
        )

        # 4. Record audit activity
        self._activity.record_registration_otp_sent(
            email=clean_email,
            ip_address=client_ip,
        )

        return UseCaseResult(
            success=True,
            reason="OTP sent successfully to your email.",
            status_code=200,
            # data={
            #     "email": clean_email,
            #     "firstName": first_name,
            #     "lastName": last_name,
            #     "expiresAt": expires_at.isoformat(),
            # },
        )

