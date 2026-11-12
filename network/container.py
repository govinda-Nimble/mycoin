from dependency_injector import containers, providers

from network.application.get_network_status import GetNetworkStatusUseCase
from network.application.initialize_genesis import InitializeGenesisUseCase
from network.application.list_nodes import ListNodesUseCase
from network.infrastructure.blockchain_repository import DjangoBlockchainRepository
from network.infrastructure.genesis_adapter import DjangoGenesisAdapter
from network.infrastructure.node_repository import DjangoNodeRepository


class NetworkContainer(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(modules=["network.views"])

    # Repositories & Adapters (Singletons)
    blockchain_repository = providers.Singleton(DjangoBlockchainRepository)
    node_repository = providers.Singleton(DjangoNodeRepository)
    genesis_adapter = providers.Singleton(DjangoGenesisAdapter)

    # Use Cases (Factories)
    get_network_status_use_case = providers.Factory(
        GetNetworkStatusUseCase,
        blockchain_reader=blockchain_repository,
        node_reader=node_repository,
    )

    list_nodes_use_case = providers.Factory(
        ListNodesUseCase,
        node_reader=node_repository,
    )

    initialize_genesis_use_case = providers.Factory(
        InitializeGenesisUseCase,
        genesis_initializer=genesis_adapter,
    )

