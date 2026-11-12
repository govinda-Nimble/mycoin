from typing import Any
from network.domain import GenesisInitializer
from network.services.genesis import GenesisConfig, initialize_blockchain


class DjangoGenesisAdapter(GenesisInitializer):
    """
    Infrastructure implementation of GenesisInitializer delegating to genesis service.
    """

    def initialize_chain(self, *, chain_id: int, chain_name: str, symbol: str = "MYC") -> Any:
        config = GenesisConfig(chain_id=chain_id, chain_name=chain_name, symbol=symbol)
        return initialize_blockchain(config)

