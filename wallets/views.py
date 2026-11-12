import logging
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dependency_injector.wiring import Provide, inject

from common.utils import get_single_error
from wallets.application.check_balance import CheckBalanceUseCase
from wallets.application.sign_transaction import SignTransactionUseCase
from wallets.container import WalletContainer
from wallets.serializers import ADDRESS_REGEX, SignTransactionSerializer

logger = logging.getLogger(__name__)


class SignTransactionAPIView(APIView):
    """
    Presentation layer: Signs a transfer transaction using the authenticated user's wallet.
    The user sends only `amount` and `receiverAddress`.
    Returns the complete signed payload in camelCase ready to be transmitted to a blockchain node.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SignTransactionSerializer

    @inject
    def post(
        self,
        request,
        use_case: SignTransactionUseCase = Provide[WalletContainer.sign_transaction_use_case],
    ):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            err_msg = get_single_error(serializer.errors)
            return Response(
                {"reason": err_msg, "error": err_msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = use_case.execute(
            user=request.user,
            receiver_address=serializer.validated_data["receiverAddress"],
            amount=serializer.validated_data["amount"],
        )

        if not result.success:
            return Response(
                {"reason": result.reason, "error": result.reason},
                status=result.status_code,
            )

        return Response(result.data, status=result.status_code)


class CheckBalanceAPIView(APIView):
    """
    Presentation layer: Checks the balance and on-chain account state for a user or address.
    Supports:
      - Authenticated user's wallet: GET /api/wallets/balance/
      - Target address query parameter: GET /api/wallets/balance/?address=0x...
      - Target address path parameter: GET /api/wallets/balance/<address>/
      - Optional chainId parameter: GET /api/wallets/balance/?chainId=1001

    Returns a standardized camelCase response containing:
      - address, balance, balanceFormatted, availableBalance, availableBalanceFormatted,
        pendingTransactionsCount, symbol, decimals, nonce, chainId, networkName, status
    """

    permission_classes = [AllowAny]

    @inject
    def get(
        self,
        request,
        address=None,
        use_case: CheckBalanceUseCase = Provide[WalletContainer.check_balance_use_case],
    ):
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

        result = use_case.execute(
            user=request.user if (request.user and request.user.is_authenticated) else None,
            address=target_address,
            chain_id=chain_id,
        )

        if not result.success:
            return Response(
                {"reason": result.reason},
                status=result.status_code,
            )

        return Response(result.data, status=result.status_code)