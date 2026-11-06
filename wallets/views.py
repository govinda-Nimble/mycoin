from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.utils import get_single_error
from wallets.serializers import SignTransactionSerializer
from wallets.services.transaction_signer import sign_transaction_for_user


class SignTransactionAPIView(APIView):
    """
    Presentation layer: Signs a transfer transaction using the authenticated user's wallet.
    The user sends only `amount` and `receiverAddress`.
    Returns the complete signed payload in camelCase ready to be transmitted to a blockchain node.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SignTransactionSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"reason": get_single_error(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            signed_tx = sign_transaction_for_user(
                user=request.user,
                receiver_address=serializer.validated_data["receiverAddress"],
                amount=serializer.validated_data["amount"],
            )
            return Response(signed_tx, status=status.HTTP_200_OK)
        except ValueError as err:
            return Response(
                {"reason": str(err)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as err:
            return Response(
                {"reason": f"Failed to sign transaction: {err}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
