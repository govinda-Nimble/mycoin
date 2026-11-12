from dependency_injector import containers, providers

from staking.application.get_validator_detail import GetValidatorDetailUseCase
from staking.application.list_validators import ListValidatorsUseCase
from staking.infrastructure.stake_repository import DjangoStakeRepository
from staking.infrastructure.validator_repository import DjangoValidatorRepository


class StakingContainer(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(modules=["staking.views"])

    # Repositories (Singletons)
    validator_repository = providers.Singleton(DjangoValidatorRepository)
    stake_repository = providers.Singleton(DjangoStakeRepository)

    # Use Cases (Factories)
    list_validators_use_case = providers.Factory(
        ListValidatorsUseCase,
        validator_reader=validator_repository,
    )

    get_validator_detail_use_case = providers.Factory(
        GetValidatorDetailUseCase,
        validator_reader=validator_repository,
        stake_reader=stake_repository,
    )

