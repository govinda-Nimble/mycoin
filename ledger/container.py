from dependency_injector import containers, providers

from ledger.application.get_transaction import GetTransactionUseCase
from ledger.application.process_mempool import ProcessMempoolUseCase
from ledger.application.validate_transaction import ValidateTransactionUseCase
from ledger.infrastructure.ledger_repository import DjangoLedgerRepository
from ledger.infrastructure.mempool_processor_adapter import DjangoMempoolProcessorAdapter
from ledger.infrastructure.transaction_validator_adapter import DjangoTransactionValidatorAdapter


class LedgerContainer(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(modules=["ledger.views"])

    # Repositories & Adapters (Singletons)
    transaction_validator = providers.Singleton(DjangoTransactionValidatorAdapter)
    ledger_repository = providers.Singleton(DjangoLedgerRepository)
    mempool_processor = providers.Singleton(DjangoMempoolProcessorAdapter)

    # Use Cases (Factories)
    validate_transaction_use_case = providers.Factory(
        ValidateTransactionUseCase,
        transaction_validator=transaction_validator,
    )

    get_transaction_use_case = providers.Factory(
        GetTransactionUseCase,
        ledger_reader=ledger_repository,
    )

    process_mempool_use_case = providers.Factory(
        ProcessMempoolUseCase,
        mempool_processor=mempool_processor,
    )

