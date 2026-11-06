from typing import Any, Optional
from django.utils import timezone
from accounts.models import UserOTP


class DjangoOTPRepository:
    """
    Implements OTPManager protocol using Django ORM and UserOTP model.
    Maintains a single OTP record per email and requestType using get_or_create.
    """

    def upsert_registration_otp(self, *, email: str, otp: str, expires_at: Any) -> UserOTP:
        clean_email = email.strip().lower()

        otp_record, created = UserOTP.objects.get_or_create(
            email=clean_email,
            requestType=UserOTP.OTPTYPES.REGISTER,
            defaults={
                "otp": otp,
                "expiresAt": expires_at,
                "attempts": 0,
                "isVerified": False,
            },
        )

        if not created:
            otp_record.otp = otp
            otp_record.expiresAt = expires_at
            otp_record.attempts = 0
            otp_record.isVerified = False
            otp_record.verifiedAt = None
            otp_record.save(
                update_fields=["otp", "expiresAt", "attempts", "isVerified", "verifiedAt", "updatedAt"]
            )

        return otp_record

    def upsert_login_otp(self, *, email: str, user: Any, otp: str, expires_at: Any) -> UserOTP:
        clean_email = email.strip().lower()

        otp_record, created = UserOTP.objects.get_or_create(
            email=clean_email,
            requestType=UserOTP.OTPTYPES.LOGIN,
            defaults={
                "user": user,
                "otp": otp,
                "expiresAt": expires_at,
                "attempts": 0,
                "isVerified": False,
            },
        )

        if not created:
            otp_record.user = user
            otp_record.otp = otp
            otp_record.expiresAt = expires_at
            otp_record.attempts = 0
            otp_record.isVerified = False
            otp_record.verifiedAt = None
            otp_record.save(
                update_fields=["user", "otp", "expiresAt", "attempts", "isVerified", "verifiedAt", "updatedAt"]
            )

        return otp_record

    def find_latest_registration_otp(self, *, email: str) -> Optional[UserOTP]:
        return UserOTP.objects.filter(
            email__iexact=email.strip(),
            requestType=UserOTP.OTPTYPES.REGISTER,
        ).first()

    def find_latest_login_otp(self, *, email: str) -> Optional[UserOTP]:
        return UserOTP.objects.filter(
            email__iexact=email.strip(),
            requestType=UserOTP.OTPTYPES.LOGIN,
        ).first()

    def mark_otp_verified(self, *, otp_record: UserOTP, user: Optional[Any] = None) -> None:
        otp_record.isVerified = True
        otp_record.verifiedAt = timezone.now()
        if user:
            otp_record.user = user
        otp_record.save(update_fields=["isVerified", "verifiedAt", "user", "updatedAt"])

    def increment_attempts(self, *, otp_record: UserOTP) -> None:
        otp_record.attempts += 1
        otp_record.save(update_fields=["attempts", "updatedAt"])
