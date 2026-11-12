from typing import Optional
from network.domain import NodeReader
from network.models import Node


class DjangoNodeRepository(NodeReader):
    """
    Infrastructure implementation of NodeReader using Django ORM.
    """

    def list_nodes(
        self,
        *,
        chain_id: Optional[int] = None,
        node_status: Optional[str] = None,
    ) -> list[Node]:
        qs = Node.objects.select_related("blockchain").all()
        if chain_id is not None:
            qs = qs.filter(blockchain__chainId=chain_id)
        if node_status:
            qs = qs.filter(status=node_status)
        return list(qs)

    def find_by_node_id(self, node_id: str) -> Optional[Node]:
        return Node.objects.filter(nodeId=node_id).select_related("blockchain").first()

