from typing import Any, Optional
from ledger.domain import MempoolBatchProcessor
from ledger.services.mempool_processor import process_mempool


class DjangoMempoolProcessorAdapter(MempoolBatchProcessor):
    """
    Infrastructure implementation of MempoolBatchProcessor delegating to the processing pipeline.
    """

    def process_batch(self, *, chain_id: Optional[int] = None, batch_size: int = 50) -> Any:
        return process_mempool(chain_id=chain_id, batch_size=batch_size)

