"""
API Views for transaction ingestion, validation, and mempool queueing.
"""

import logging
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from dependency_injector.wiring import Provide, inject

from common.utils import get_single_error
from ledger.application.get_transaction import GetTransactionUseCase
from ledger.application.validate_transaction import ValidateTransactionUseCase
from ledger.container import LedgerContainer
from ledger.serializers import CheckTransactionSerializer

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
