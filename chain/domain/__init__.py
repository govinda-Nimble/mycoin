from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


@dataclass
class UseCaseResult:
    success: bool
    reason: str
    status_code: int = 200
    data: Optional[Dict[str, Any]] = None


class BlockchainReader(Protocol):
    def get_active(self) -> Any: ...
    def get_by_chain_id(self, chain_id: int) -> Any: ...


class GenesisInitializer(Protocol):
    def initialize_chain(self, chain_id: int, chain_name: str, symbol: str = "MYC") -> Any: ...

