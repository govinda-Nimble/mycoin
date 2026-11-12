"""
API Views for Network status, node topology, and genesis bootstrapping.
"""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from dependency_injector.wiring import Provide, inject

from network.application.get_network_status import GetNetworkStatusUseCase
from network.application.initialize_genesis import InitializeGenesisUseCase
from network.application.list_nodes import ListNodesUseCase
from network.container import NetworkContainer


class NetworkStatusAPIView(APIView):
    """
    Presentation layer: Returns current network status, chain height, and online node count.
    Supports GET /api/network/status/ and GET /api/network/status/?chainId=1001
    """

    permission_classes = [AllowAny]

    @inject
    def get(
        self,
        request,
        use_case: GetNetworkStatusUseCase = Provide[NetworkContainer.get_network_status_use_case],
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


class NodeListAPIView(APIView):
    """
    Presentation layer: Returns registered blockchain nodes.
    Supports optional query filters: ?chainId=1001&status=ONLINE
    """

    permission_classes = [AllowAny]

    @inject
    def get(
        self,
        request,
        use_case: ListNodesUseCase = Provide[NetworkContainer.list_nodes_use_case],
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

        node_status = request.query_params.get("status")
        result = use_case.execute(chain_id=chain_id, node_status=node_status)

        return Response(
            {"success": True, "data": result.data},
            status=result.status_code,
        )


class GenesisInitAPIView(APIView):
    """
    Presentation layer: Initializes a new genesis blockchain network.
    """

    permission_classes = [AllowAny]

    @inject
    def post(
        self,
        request,
        use_case: InitializeGenesisUseCase = Provide[NetworkContainer.initialize_genesis_use_case],
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
