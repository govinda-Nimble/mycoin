from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class UseCaseResult:
    """Standardized response across all network use cases."""
    success: bool
    reason: str
    status_code: int
    data: Optional[Any] = None


class BlockchainReader(Protocol):
    """Abstract contract for reading blockchain metadata and state."""

    def get_active(self) -> Optional[Any]:
        ...

    def get_by_chain_id(self, chain_id: int) -> Optional[Any]:
        ...


class NodeReader(Protocol):
    """Abstract contract for reading network node records."""

    def list_nodes(
        self,
        *,
        chain_id: Optional[int] = None,
        node_status: Optional[str] = None,
    ) -> list[Any]:
        ...

    def find_by_node_id(self, node_id: str) -> Optional[Any]:
        ...


class GenesisInitializer(Protocol):
    """Abstract contract for genesis blockchain initialization."""

    def initialize_chain(self, *, chain_id: int, chain_name: str, symbol: str = "MYC") -> Any:
        ...

