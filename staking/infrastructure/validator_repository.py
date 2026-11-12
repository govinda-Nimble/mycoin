from typing import Optional
from staking.domain import ValidatorReader
from staking.models import Validator


class DjangoValidatorRepository(ValidatorReader):
    """
    Infrastructure implementation of ValidatorReader using Django ORM.
    """

    def list_validators(
        self,
        *,
        chain_id: Optional[int] = None,
        validator_status: Optional[str] = None,
    ) -> list[Validator]:
        qs = Validator.objects.select_related("account", "account__blockchain").all()
        if chain_id is not None:
            qs = qs.filter(account__blockchain__chainId=chain_id)
        if validator_status:
            qs = qs.filter(status=validator_status)
        return list(qs)

    def find_by_id(self, validator_id: str) -> Optional[Validator]:
        try:
            return Validator.objects.filter(id=validator_id).select_related("account").first()
        except Exception:
            return None

    def find_by_address(self, address: str) -> Optional[Validator]:
        clean_addr = address.strip().lower()
        return Validator.objects.filter(account__address=clean_addr).select_related("account").first()

