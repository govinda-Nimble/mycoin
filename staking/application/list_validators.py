from typing import Optional
from staking.domain import UseCaseResult, ValidatorReader


class ListValidatorsUseCase:
    """
    Application use case: Queries and returns validators with their status and stake info.
    """

    def __init__(self, validator_reader: ValidatorReader):
        self._validator_reader = validator_reader

    def execute(
        self,
        *,
        chain_id: Optional[int] = None,
        validator_status: Optional[str] = None,
    ) -> UseCaseResult:
        validators = self._validator_reader.list_validators(
            chain_id=chain_id,
            validator_status=validator_status,
        )

        data = [
            {
                "id": str(v.id),
                "address": v.account.address if v.account else None,
                "publicKey": v.publicKey,
                "status": v.status,
                "totalStake": str(v.totalStake),
                "commissionPercent": str(v.commissionPercent),
                "activatedAt": v.activatedAt.isoformat() if v.activatedAt else None,
                "lastActiveAt": v.lastActiveAt.isoformat() if v.lastActiveAt else None,
            }
            for v in validators
        ]

        return UseCaseResult(
            success=True,
            reason="Validators retrieved successfully.",
            status_code=200,
            data=data,
        )

