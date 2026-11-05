import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DjangoActivityRecorder:
    """
    Implements ActivityRecorder protocol.
    Records audit and activity events. Can easily be extended by teammates to write
    to an ActivityLog table or external analytics without changing the use cases.
    """

    def record_login(self, *, user: Any, ip_address: Optional[str]) -> None:
        logger.info(
            "User login recorded: user_id=%s, email=%s, ip_address=%s",
            getattr(user, "id", None),
            getattr(user, "email", None),
            ip_address,
        )

    def record_logout(self, *, user_id: Optional[str], ip_address: Optional[str]) -> None:
        logger.info(
            "User logout recorded: user_id=%s, ip_address=%s",
            user_id,
            ip_address,
        )

    def record_token_refreshed(self, *, ip_address: Optional[str]) -> None:
        logger.info(
            "Token refresh recorded: ip_address=%s",
            ip_address,
        )

    def record_registration_otp_sent(self, *, email: str, ip_address: Optional[str]) -> None:
        logger.info(
            "Registration OTP sent: email=%s, ip_address=%s",
            email,
            ip_address,
        )

    def record_registration_completed(self, *, user: Any, ip_address: Optional[str]) -> None:
        logger.info(
            "User registration completed: user_id=%s, email=%s, ip_address=%s",
            getattr(user, "id", None),
            getattr(user, "email", None),
            ip_address,
        )

    def record_login_otp_sent(self, *, user: Any, ip_address: Optional[str]) -> None:
        logger.info(
            "Login OTP sent: user_id=%s, email=%s, ip_address=%s",
            getattr(user, "id", None),
            getattr(user, "email", None),
            ip_address,
        )
