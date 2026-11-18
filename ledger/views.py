"""
API Views for transaction ingestion, validation, and mempool queueing.
"""

import logging
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from dependency_injector.wiring import Provide, inject

from common.utils import get_single_error
from ledger.application.get_transaction import GetTransactionUseCase
from ledger.application.validate_transaction import ValidateTransactionUseCase
from ledger.container import LedgerContainer
from ledger.models import Block, BlockTransaction, Transaction
from ledger.serializers import BlockSerializer, CheckTransactionSerializer

logger = logging.getLogger(__name__)


class CheckTransactionAPIView(APIView):
    """
    Presentation layer: Validates an incoming signed transaction payload across:
    1. Check sender
    2. Check receiver
    3. Verify public key
    4. Verify signature
    5. Check nonce
    6. Check balance
    7. Check gas
    8. Check duplicate hash

    Upon successful validation:
    - Saves the Transaction with status=PENDING
    - Creates a MempoolTransaction with status=ACTIVE
    - Returns standardized camelCase transaction metadata
    """

    permission_classes = [AllowAny]
    serializer_class = CheckTransactionSerializer

    @inject
    def post(
        self,
        request,
        use_case: ValidateTransactionUseCase = Provide[LedgerContainer.validate_transaction_use_case],
    ):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "reason": get_single_error(serializer.errors),
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = use_case.execute(payload=serializer.validated_data)

        if not result.success:
            err_body = {
                "success": False,
                "reason": result.reason,
            }
            if result.step:
                err_body["step"] = result.step
            return Response(err_body, status=result.status_code)

        return Response(
            {
                "success": True,
                "message": result.reason,
                "data": result.data,
            },
            status=result.status_code,
        )


class TransactionDetailAPIView(APIView):
    """
    Presentation layer: Retrieves details for a specific transaction by hash.
    """

    permission_classes = [AllowAny]

    @inject
    def get(
        self,
        request,
        tx_hash: str,
        use_case: GetTransactionUseCase = Provide[LedgerContainer.get_transaction_use_case],
    ):
        result = use_case.execute(tx_hash=tx_hash)
        if not result.success:
            return Response(
                {"success": False, "reason": result.reason},
                status=result.status_code,
            )

        return Response(
            {"success": True, "data": result.data},
            status=result.status_code,
        )


class DataPagination(PageNumberPagination):
    """
    Pagination class for listings. Defaults to 10 records per page.
    Supports 'page', and 'pageSize' query parameters.
    """

    page_size = 10
    page_size_query_param = "pageSize"
    max_page_size = 100
    page_query_param = "page"

    def get_page_size(self, request):
        if "pageSize" in request.query_params:
            try:
                size = int(request.query_params["pageSize"])
                if size > 0:
                    return min(size, self.max_page_size)
            except (ValueError, TypeError):
                pass
        return super().get_page_size(request)

    def get_paginated_response(self):
        return {
            "count": self.page.paginator.count,
            "totalPages": self.page.paginator.num_pages,
            "currentPage": self.page.number,
            "pageSize": self.get_page_size(self.request) or self.page_size,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
        }


class BlockListAPIView(APIView):
    """
    Presentation layer: Lists blocks ordered from newest to oldest (-height)
    with pagination (default 10 blocks per page).

    Supported query parameters:
      - page: page number (default 1)
      - pageSize: number of blocks per page (default 10)
      - chainId: filter blocks by blockchain chain ID
      - status: filter blocks by status (e.g. FINALIZED, PROPOSED)
    """

    permission_classes = [AllowAny]
    pagination_class = DataPagination

    def get(self, request):
        queryset = Block.objects.select_related("blockchain", "proposer__account").all().order_by("-height")

        # chain_id_param = request.query_params.get("chainId")
        # if chain_id_param:
        #     try:
        #         queryset = queryset.filter(blockchain__chainId=int(chain_id_param))
        #     except (ValueError, TypeError):
        #         return Response(
        #             {"success": False, "reason": "chainId must be a valid integer."},
        #             status=status.HTTP_400_BAD_REQUEST,
        #         )

        # status_param = request.query_params.get("status")
        # if status_param:
        #     queryset = queryset.filter(status=status_param.upper())

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)

        if page is not None:
            serializer = BlockSerializer(page, many=True)
            pagination_data = paginator.get_paginated_response()
            blocks_data = serializer.data
        else:
            # Fallback if pagination isn't triggered
            serializer = BlockSerializer(queryset, many=True)
            blocks_data = serializer.data
            pagination_data = {}

        return Response({
            "success": True, 
            "data": {
                "blocksData": blocks_data,
                "paginationData": pagination_data
            }
        }, status=status.HTTP_200_OK)


class BlockTransactionsAPIView(APIView):
    """
    Presentation layer: Returns all transactions contained in a single block
    using the block hash.
    """

    permission_classes = [AllowAny]

    def get(self, request, block_hash: str):
        clean_hash = str(block_hash).strip().lower()
        try:
            block = Block.objects.select_related("blockchain").get(blockHash=clean_hash)
        except Block.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "reason": f"Block with hash '{block_hash}' not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        block_txs = (
            BlockTransaction.objects.filter(block=block)
            .select_related("transaction", "transaction__sender", "transaction__receipt")
            .order_by("txIndex")
        )

        transactions_data = []
        if block_txs.exists():
            for btx in block_txs:
                tx = btx.transaction
                receipt = getattr(tx, "receipt", None)
                transactions_data.append({
                    "txHash": tx.hash,
                    "txIndex": btx.txIndex,
                    "senderAddress": tx.sender.address if tx.sender else None,
                    "receiverAddress": tx.receiverAddress,
                    "txType": tx.txType,
                    "amount": str(tx.amount),
                    "nonce": tx.nonce,
                    "gasLimit": tx.gasLimit,
                    "gasPrice": str(tx.gasPrice),
                    "feePaid": tx.feePaid,
                    "status": tx.status,
                    "receiptStatus": receipt.status if receipt else None,
                    "gasUsed": receipt.gasUsed if receipt else None,
                    "createdAt": tx.createdAt.isoformat() if tx.createdAt else None,
                })
        else:
            direct_txs = (
                Transaction.objects.filter(block=block)
                .select_related("sender", "receipt")
                .order_by("createdAt")
            )
            for idx, tx in enumerate(direct_txs):
                receipt = getattr(tx, "receipt", None)
                transactions_data.append({
                    "txHash": tx.hash,
                    "txIndex": idx,
                    "senderAddress": tx.sender.address if tx.sender else None,
                    "receiverAddress": tx.receiverAddress,
                    "txType": tx.txType,
                    "amount": str(tx.amount),
                    "nonce": tx.nonce,
                    "gasLimit": tx.gasLimit,
                    "gasPrice": str(tx.gasPrice),
                    "feePaid": tx.feePaid,
                    "status": tx.status,
                    "receiptStatus": receipt.status if receipt else None,
                    "gasUsed": receipt.gasUsed if receipt else None,
                    "createdAt": tx.createdAt.isoformat() if tx.createdAt else None,
                })

        return Response(
            {
                "success": True,
                "data": {
                    "blockHash": block.blockHash,
                    "blockHeight": block.height,
                    "chainId": block.blockchain.chainId,
                    "transactionCount": len(transactions_data),
                    "transactions": transactions_data,
                },
            },
            status=status.HTTP_200_OK,
        )
