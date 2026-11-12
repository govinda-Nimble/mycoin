from staking.domain import StakeReader, UseCaseResult, ValidatorReader


class GetValidatorDetailUseCase:
    """
    Application use case: Queries a single validator's details, commission, and active stakes.
    """

    def __init__(self, validator_reader: ValidatorReader, stake_reader: StakeReader):
        self._validator_reader = validator_reader
        self._stake_reader = stake_reader

    def execute(self, *, validator_id: str) -> UseCaseResult:
        validator = self._validator_reader.find_by_id(validator_id)
        if not validator:
            validator = self._validator_reader.find_by_address(validator_id)

        if not validator:
            return UseCaseResult(
                success=False,
                reason=f"Validator '{validator_id}' not found.",
                status_code=404,
            )

        stakes = self._stake_reader.list_stakes_for_validator(str(validator.id))

        stakes_data = [
            {
                "id": str(s.id),
                "stakerAddress": s.stakerAccount.address if s.stakerAccount else None,
                "amount": str(s.amount),
                "status": s.status,
                "createdAt": s.createdAt.isoformat() if s.createdAt else None,
            }
            for s in stakes
        ]

        data = {
            "id": str(validator.id),
            "address": validator.account.address if validator.account else None,
            "publicKey": validator.publicKey,
            "status": validator.status,
            "totalStake": str(validator.totalStake),
            "commissionPercent": str(validator.commissionPercent),
            "activatedAt": validator.activatedAt.isoformat() if validator.activatedAt else None,
            "stakes": stakes_data,
        }

        return UseCaseResult(
            success=True,
            reason="Validator detail retrieved successfully.",
            status_code=200,
            data=data,
        )
