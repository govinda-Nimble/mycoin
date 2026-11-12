from typing import Optional
from ledger.domain import LedgerReader
from ledger.models import Block, Transaction


class DjangoLedgerRepository(LedgerReader):
    """
    Infrastructure implementation of LedgerReader using Django ORM.
    """

    def find_transaction_by_hash(self, tx_hash: str) -> Optional[Transaction]:
        clean_hash = tx_hash.strip().lower()
        if not clean_hash.startswith("0x"):
            clean_hash = f"0x{clean_hash}"
        return (
            Transaction.objects.filter(hash=clean_hash)
            .select_related("sender", "receiver", "block")
            .first()
            or Transaction.objects.filter(hash=tx_hash.strip().lower())
            .select_related("sender", "receiver", "block")
            .first()
        )

    def find_block_by_height(self, chain_id: int, height: int) -> Optional[Block]:
        return (
            Block.objects.filter(blockchain__chainId=chain_id, height=height)
            .select_related("blockchain", "proposer")
            .first()
        )

