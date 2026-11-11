import logging
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.utils import get_single_error
from wallets.serializers import ADDRESS_REGEX, AccountBalanceSerializer, SignTransactionSerializer
from wallets.services.transaction_signer import sign_transaction_for_user
from wallets.services.wallet_service import get_account_balance

logger = logging.getLogger(__name__)


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


class CheckBalanceAPIView(APIView):
    """
    Presentation layer: Checks the balance and on-chain account state for a user or address.
    Supports:
      - Authenticated user's wallet: GET /api/wallets/balance/
      - Target address query parameter: GET /api/wallets/balance/?address=0x...
      - Target address path parameter: GET /api/wallets/balance/<address>/
      - Optional chainId parameter: GET /api/wallets/balance/?chainId=1001

    Returns a standardized camelCase response containing:
      - address
      - balance (smallest units)
      - balanceFormatted (decimal string)
      - availableBalance (after pending mempool deductions)
      - availableBalanceFormatted
      - pendingTransactionsCount
      - symbol
      - decimals
      - nonce
      - chainId
      - networkName
      - status
    """

    permission_classes = [AllowAny]

    def get(self, request, address=None):
        target_address = address or request.query_params.get("address")
        chain_id_param = request.query_params.get("chainId")

        chain_id = None
        if chain_id_param is not None:
            try:
                chain_id = int(chain_id_param)
            except ValueError:
                return Response(
                    {"reason": "chainId must be a valid integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if target_address:
            target_address = target_address.strip()
            if not ADDRESS_REGEX.match(target_address):
                return Response(
                    {"reason": "Must be '0x' followed by 40 hexadecimal characters."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            if not request.user or not request.user.is_authenticated:
                return Response(
                    {"reason": "Authentication credentials were not provided or address parameter is required."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        try:
            balance_data = get_account_balance(
                user=request.user if (request.user and request.user.is_authenticated) else None,
                address=target_address,
                chain_id=chain_id,
            )
            return Response(balance_data, status=status.HTTP_200_OK)
        except ValueError as err:
            return Response(
                {"reason": str(err)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as err:
            logger.exception("Failed to retrieve balance: %s", err)
            return Response(
                {"reason": f"Failed to retrieve balance: {err}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

