from typing import Optional
from network.domain import NodeReader, UseCaseResult


class ListNodesUseCase:
    """
    Application use case: Lists peer nodes registered on the network.
    """

    def __init__(self, node_reader: NodeReader):
        self._node_reader = node_reader

    def execute(
        self,
        *,
        chain_id: Optional[int] = None,
        node_status: Optional[str] = None,
    ) -> UseCaseResult:
        nodes = self._node_reader.list_nodes(chain_id=chain_id, node_status=node_status)

        nodes_data = [
            {
                "id": str(n.id),
                "nodeId": n.nodeId,
                "nodeType": n.nodeType,
                "status": n.status,
                "endpoint": n.endpoint,
                "chainId": n.blockchain.chainId if n.blockchain else None,
                "lastHeartbeat": n.lastHeartbeat.isoformat() if n.lastHeartbeat else None,
            }
            for n in nodes
        ]

        return UseCaseResult(
            success=True,
            reason="Nodes retrieved successfully.",
            status_code=200,
            data=nodes_data,
        )

