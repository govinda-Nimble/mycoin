"""
API Views for transaction ingestion, validation, and mempool queueing.
"""

import logging
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.utils import get_single_error
from ledger.serializers import CheckTransactionSerializer
from ledger.services.transaction_validator import (
    TransactionValidationError,
    validate_and_enqueue_transaction,
)

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

    permission_classes = [IsAuthenticated]
    serializer_class = CheckTransactionSerializer

    def post(self, request):
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

        try:
            result = validate_and_enqueue_transaction(serializer.validated_data)
            tx = result.transaction
            mempool = result.mempool_entry

            return Response(
                {
                    "success": True,
                    "message": result.message,
                    "data": {
                        "txHash": result.tx_hash,
                        "senderAddress": tx.sender.address,
                        "receiverAddress": tx.receiverAddress,
                        "amount": str(tx.amount),
                        "nonce": tx.nonce,
                        "gasLimit": tx.gasLimit,
                        "gasPrice": str(tx.gasPrice),
                        "fee": tx.gasLimit * tx.gasPrice,
                        "status": tx.status,
                        "mempoolStatus": mempool.status,
                        "mempoolEntryId": str(mempool.id),
                        "nodeId": mempool.node.nodeId,
                        "arrivalTime": mempool.arrivalTime.isoformat(),
                        "expiresAt": mempool.expiresAt.isoformat(),
                    },
                },
                status=status.HTTP_201_CREATED,
            )
        except TransactionValidationError as err:
            return Response(
                {
                    "success": False,
                    "reason": err.message,
                    "step": err.step,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as err:
            logger.exception("Unexpected error in CheckTransactionAPIView: %s", err)
            return Response(
                {
                    "success": False,
                    "reason": f"Internal transaction processing error: {str(err)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
