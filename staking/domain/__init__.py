from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class UseCaseResult:
    """Standardized response across all staking use cases."""
    success: bool
    reason: str
    status_code: int
    data: Optional[Any] = None


class ValidatorReader(Protocol):
    """Abstract contract for reading PoS validator data."""

    def list_validators(
        self,
        *,
        chain_id: Optional[int] = None,
        validator_status: Optional[str] = None,
    ) -> list[Any]:
        ...

    def find_by_id(self, validator_id: str) -> Optional[Any]:
        ...

    def find_by_address(self, address: str) -> Optional[Any]:
        ...


class StakeReader(Protocol):
    """Abstract contract for reading delegations and validator stakes."""

    def list_stakes_for_validator(self, validator_id: str) -> list[Any]:
        ...

