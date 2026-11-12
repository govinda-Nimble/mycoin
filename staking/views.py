"""
API Views for Proof-of-Stake validator registry and delegation metrics.
"""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from dependency_injector.wiring import Provide, inject

from staking.application.get_validator_detail import GetValidatorDetailUseCase
from staking.application.list_validators import ListValidatorsUseCase
from staking.container import StakingContainer


class ValidatorListAPIView(APIView):
    """
    Presentation layer: Returns a list of active Proof-of-Stake validators.
    Supports optional query filters: ?chainId=1001&status=ACTIVE
    """

    permission_classes = [AllowAny]

    @inject
    def get(
        self,
        request,
        use_case: ListValidatorsUseCase = Provide[StakingContainer.list_validators_use_case],
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

        validator_status = request.query_params.get("status")
        result = use_case.execute(chain_id=chain_id, validator_status=validator_status)

        return Response(
            {"success": True, "data": result.data},
            status=result.status_code,
        )


class ValidatorDetailAPIView(APIView):
    """
    Presentation layer: Returns details and stake allocations for a validator.
    """

    permission_classes = [AllowAny]

    @inject
    def get(
        self,
        request,
        validator_id: str,
        use_case: GetValidatorDetailUseCase = Provide[StakingContainer.get_validator_detail_use_case],
    ):
        result = use_case.execute(validator_id=validator_id)
        if not result.success:
            return Response(
                {"success": False, "reason": result.reason},
                status=result.status_code,
            )

        return Response(
            {"success": True, "data": result.data},
            status=result.status_code,
        )
