"""
API Views for Chain status and genesis bootstrapping.
"""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from dependency_injector.wiring import Provide, inject

from chain.application.get_chain_status import GetChainStatusUseCase
from chain.application.initialize_genesis import InitializeGenesisUseCase
from chain.container import ChainContainer


class ChainStatusAPIView(APIView):
    """
    Presentation layer: Returns current chain status and parameters.
    Supports GET /api/chain/status/ and GET /api/chain/status/?chainId=1001
    """

    permission_classes = [AllowAny]

    @inject
    def get(
        self,
        request,
        use_case: GetChainStatusUseCase = Provide[ChainContainer.get_chain_status_use_case],
    ):
        chain_id_param = request.query_params.get("chainId")
        chain_id = None
        if chain_id_param:
            try:
                chain_id = int(chain_id_param)
            except ValueError:
                return Response(
                    {"success": False, "reason": "chainId must be a valid integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        result = use_case.execute(chain_id=chain_id)
        if not result.success:
            return Response(
                {"success": False, "reason": result.reason},
                status=result.status_code,
            )

        return Response(
            {"success": True, "data": result.data},
            status=result.status_code,
        )


class GenesisInitAPIView(APIView):
    """
    Presentation layer: Initializes a new genesis blockchain network.
    Supports POST /api/chain/genesis/
    """

    permission_classes = [AllowAny]

    @inject
    def post(
        self,
        request,
        use_case: InitializeGenesisUseCase = Provide[ChainContainer.initialize_genesis_use_case],
    ):
        chain_id = request.data.get("chainId")
        chain_name = request.data.get("chainName")
        symbol = request.data.get("symbol", "MYC")

        if not chain_id or not chain_name:
            return Response(
                {"success": False, "reason": "chainId and chainName are required fields."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            chain_id_int = int(chain_id)
        except ValueError:
            return Response(
                {"success": False, "reason": "chainId must be a valid integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = use_case.execute(
            chain_id=chain_id_int,
            chain_name=str(chain_name).strip(),
            symbol=str(symbol).strip(),
        )

        return Response(
            {"success": result.success, "reason": result.reason, "data": result.data},
            status=result.status_code,
        )
