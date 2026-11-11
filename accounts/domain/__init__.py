from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class UseCaseResult:
    """Standardized response across all use cases."""
    success: bool
    reason: str
    status_code: int
    data: Optional[Any] = None


class UserReader(Protocol):
    """Abstract contract for reading user data."""

    def find_active_by_email(self, email: str) -> Optional[Any]:
        ...

    def find_by_id(self, user_id: str) -> Optional[Any]:
        ...

    def exists_by_email(self, email: str) -> bool:
        ...


class UserWriter(Protocol):
    """Abstract contract for creating or updating user state."""

    def update_last_login(self, user: Any) -> None:
        ...

    def create_user(
        self,
        *,
        email: str,
        firstName: str,
        lastName: str,
        password: Optional[str] = None,
        is_email_verified: bool = True,
    ) -> Any:
        ...


class TokenManager(Protocol):
    """Abstract contract for token creation, refresh, and revocation."""

    def create_token_pair_for_user(self, user: Any) -> dict[str, Any]:
        ...

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        ...

    def blacklist_token(self, refresh_token: str) -> bool:
        ...


class OTPManager(Protocol):
    """Abstract contract for OTP persistence and verification."""

    def upsert_registration_otp(self, *, email: str, otp: str, expires_at: Any) -> Any:
        ...

    def upsert_login_otp(self, *, email: str, user: Any, otp: str, expires_at: Any) -> Any:
        ...

    def find_latest_registration_otp(self, *, email: str) -> Optional[Any]:
        ...

    def find_latest_login_otp(self, *, email: str) -> Optional[Any]:
        ...

    def mark_otp_verified(self, *, otp_record: Any, user: Optional[Any] = None) -> None:
        ...

    def increment_attempts(self, *, otp_record: Any) -> None:
        ...


class ActivityRecorder(Protocol):
    """Abstract contract for security audit logging."""

    def record_login(self, *, user: Any, ip_address: Optional[str]) -> None:
        ...

    def record_logout(self, *, user_id: Optional[str], ip_address: Optional[str]) -> None:
        ...

    def record_token_refreshed(self, *, ip_address: Optional[str]) -> None:
        ...

    def record_registration_otp_sent(self, *, email: str, ip_address: Optional[str]) -> None:
        ...

    def record_registration_completed(self, *, user: Any, ip_address: Optional[str]) -> None:
        ...

    def record_login_otp_sent(self, *, user: Any, ip_address: Optional[str]) -> None:
        ...


class WalletCreator(Protocol):
    """Abstract contract for creating a blockchain wallet and provisioning on-chain account for a user."""

    def create_wallet_for_user(self, user: Any) -> Any:
        ...

    def create_account_for_wallet(self, user: Any, wallet: Any) -> Any:
        ...
