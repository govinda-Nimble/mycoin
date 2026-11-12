from staking.domain import StakeReader
from staking.models import Stake


class DjangoStakeRepository(StakeReader):
    """
    Infrastructure implementation of StakeReader using Django ORM.
    """

    def list_stakes_for_validator(self, validator_id: str) -> list[Stake]:
        return list(
            Stake.objects.filter(validator_id=validator_id)
            .select_related("stakerAccount")
            .all()
        )
