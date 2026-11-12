import logging
from network.domain import GenesisInitializer, UseCaseResult

logger = logging.getLogger(__name__)


class InitializeGenesisUseCase:
    """
    Application use case: Orchestrates genesis block initialization and network bootstrapping.
    """

    def __init__(self, genesis_initializer: GenesisInitializer):
        self._initializer = genesis_initializer

    def execute(
        self,
        *,
        chain_id: int,
        chain_name: str,
        symbol: str = "MYC",
    ) -> UseCaseResult:
        try:
            res = self._initializer.initialize_chain(
                chain_id=chain_id,
                chain_name=chain_name,
                symbol=symbol,
            )
            return UseCaseResult(
                success=True,
                reason=f"Genesis blockchain '{chain_name}' initialized successfully.",
                status_code=201,
                data={
                    "chainId": res.blockchain.chainId,
                    "chainName": res.blockchain.name,
                    "genesisBlockHash": res.genesis_block.blockHash,
                    "treasuryBalance": str(res.treasury_account.balance),
                },
            )
        except Exception as err:
            logger.exception("Failed to initialize genesis: %s", err)
            return UseCaseResult(
                success=False,
                reason=f"Failed to initialize genesis: {err}",
                status_code=400,
            )

