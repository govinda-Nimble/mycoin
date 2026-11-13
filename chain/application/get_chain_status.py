from typing import Optional
from chain.domain import BlockchainReader, UseCaseResult


class GetChainStatusUseCase:
    """
    Application use case: Retrieves current blockchain status and chain parameters.
    """

    def __init__(self, blockchain_reader: BlockchainReader):
        self._blockchain_reader = blockchain_reader

    def execute(self, *, chain_id: Optional[int] = None) -> UseCaseResult:
        if chain_id is not None:
            blockchain = self._blockchain_reader.get_by_chain_id(chain_id)
        else:
            blockchain = self._blockchain_reader.get_active()

        if not blockchain:
            return UseCaseResult(
                success=False,
                reason="No active blockchain network found.",
                status_code=404,
            )

        tip = getattr(blockchain, "latestFinalizedBlock", None)

        data = {
            "chainId": blockchain.chainId,
            "chainName": blockchain.name,
            "symbol": blockchain.symbol,
            "decimals": blockchain.decimals,
            "status": blockchain.status,
            "latestBlockHeight": tip.height if tip else 0,
            "latestBlockHash": tip.blockHash if tip else None,
            "blockTimeSeconds": blockchain.blockTimeSeconds,
            "maxBlockGas": blockchain.maxBlockGas,
            "minGasPrice": blockchain.minGasPrice,
            "baseTransferGas": blockchain.baseTransferGas,
            "blockReward": blockchain.blockReward,
        }

        return UseCaseResult(
            success=True,
            reason="Chain status retrieved successfully.",
            status_code=200,
            data=data,
        )

