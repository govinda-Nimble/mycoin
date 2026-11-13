from typing import Optional
from chain.domain import BlockchainReader
from chain.models import Blockchain, BlockchainStatus


class DjangoBlockchainRepository(BlockchainReader):
    def get_active(self) -> Optional[Blockchain]:
        return Blockchain.objects.filter(status=BlockchainStatus.ACTIVE).first()

    def get_by_chain_id(self, chain_id: int) -> Optional[Blockchain]:
        return Blockchain.objects.filter(chainId=chain_id).first()

