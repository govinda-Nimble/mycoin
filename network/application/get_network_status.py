from typing import Optional
from network.domain import BlockchainReader, NodeReader, UseCaseResult


class GetNetworkStatusUseCase:
    """
    Application use case: Retrieves current network status, chain info, and node statistics.
    """

    def __init__(self, blockchain_reader: BlockchainReader, node_reader: NodeReader):
        self._blockchain_reader = blockchain_reader
        self._node_reader = node_reader

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

        nodes = self._node_reader.list_nodes(chain_id=blockchain.chainId)
        online_nodes = [n for n in nodes if getattr(n, "status", "") == "ONLINE"]

        tip = getattr(blockchain, "latestFinalizedBlock", None)

        data = {
            "chainId": blockchain.chainId,
            "chainName": blockchain.name,
            "symbol": blockchain.symbol,
            "decimals": blockchain.decimals,
            "status": blockchain.status,
            "latestBlockHeight": tip.height if tip else 0,
            "latestBlockHash": tip.blockHash if tip else None,
            "totalNodes": len(nodes),
            "onlineNodes": len(online_nodes),
        }

        return UseCaseResult(
            success=True,
            reason="Network status retrieved successfully.",
            status_code=200,
            data=data,
        )

