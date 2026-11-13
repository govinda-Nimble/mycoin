from chain.domain import GenesisInitializer
from chain.services.genesis import GenesisConfig, GenesisInitializationResult, initialize_blockchain


class DjangoGenesisAdapter(GenesisInitializer):
    def initialize_chain(self, chain_id: int, chain_name: str, symbol: str = "MYC") -> GenesisInitializationResult:
        config = GenesisConfig(
            chain_id=chain_id,
            chain_name=chain_name,
            symbol=symbol,
        )
        return initialize_blockchain(config)

