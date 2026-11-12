from typing import Optional
from network.domain import BlockchainReader
from network.models import Blockchain, BlockchainStatus


class DjangoBlockchainRepository(BlockchainReader):
    """
    Infrastructure implementation of BlockchainReader using Django ORM.
    """

    def get_active(self) -> Optional[Blockchain]:
        return (
            Blockchain.objects.filter(status=BlockchainStatus.ACTIVE)
            .select_related("latestFinalizedBlock")
            .first()
        )

    def get_by_chain_id(self, chain_id: int) -> Optional[Blockchain]:
        return (
            Blockchain.objects.filter(chainId=chain_id)
            .select_related("latestFinalizedBlock")
            .first()
        )

