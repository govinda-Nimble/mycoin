import logging
from typing import Optional
from ledger.domain import MempoolBatchProcessor, UseCaseResult

logger = logging.getLogger(__name__)


class ProcessMempoolUseCase:
    """
    Application use case: Orchestrates mempool candidate batch processing and block production.
    """

    def __init__(self, mempool_processor: MempoolBatchProcessor):
        self._processor = mempool_processor

    def execute(self, *, chain_id: Optional[int] = None, batch_size: int = 50) -> UseCaseResult:
        try:
            result = self._processor.process_batch(chain_id=chain_id, batch_size=batch_size)
            return UseCaseResult(
                success=True,
                reason=f"Mempool processing completed: status={result.status}, included={result.included_count}",
                status_code=200,
                data={
                    "status": result.status,
                    "includedCount": result.included_count,
                    "evictedCount": result.evicted_count,
                    "blockHeight": result.block.height if result.block else None,
                },
            )
        except Exception as err:
            logger.exception("Failed to process mempool: %s", err)
            return UseCaseResult(
                success=False,
                reason=f"Failed to process mempool: {err}",
                status_code=500,
            )

