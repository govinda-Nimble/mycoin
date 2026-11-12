from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class UseCaseResult:
    """Standardized response across all wallet use cases."""
    success: bool
    reason: str
    status_code: int
    data: Optional[Any] = None


class WalletReader(Protocol):
    """Abstract contract for reading wallet data."""

    def find_by_user(self, user: Any) -> Optional[Any]:
        ...

    def find_by_address(self, address: str) -> Optional[Any]:
        ...


class WalletWriter(Protocol):
    """Abstract contract for wallet creation."""

    def create_wallet_for_user(self, user: Any, name: str = "") -> Any:
        ...


class AccountReader(Protocol):
    """Abstract contract for reading on-chain account balances."""

    def get_balance(
        self,
        *,
        user: Optional[Any] = None,
        address: Optional[str] = None,
        chain_id: Optional[int] = None,
    ) -> dict[str, Any]:
        ...


class TransactionSigner(Protocol):
    """Abstract contract for signing transactions."""

    def sign_transaction(
        self,
        *,
        user: Any,
        receiver_address: str,
        amount: str,
    ) -> dict[str, Any]:
        ...

