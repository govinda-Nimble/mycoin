from dependency_injector import containers, providers

from chain.application.get_chain_status import GetChainStatusUseCase
from chain.application.initialize_genesis import InitializeGenesisUseCase
from chain.infrastructure.blockchain_repository import DjangoBlockchainRepository
from chain.infrastructure.genesis_adapter import DjangoGenesisAdapter


class ChainContainer(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(modules=["chain.views"])

    # Repositories & Adapters (Singletons)
    blockchain_repository = providers.Singleton(DjangoBlockchainRepository)
    genesis_adapter = providers.Singleton(DjangoGenesisAdapter)

    # Use Cases (Factories)
    get_chain_status_use_case = providers.Factory(
        GetChainStatusUseCase,
        blockchain_reader=blockchain_repository,
    )

    initialize_genesis_use_case = providers.Factory(
        InitializeGenesisUseCase,
        genesis_initializer=genesis_adapter,
    )

