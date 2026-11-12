from dependency_injector import containers, providers

from wallets.application.check_balance import CheckBalanceUseCase
from wallets.application.create_wallet import CreateWalletUseCase
from wallets.application.sign_transaction import SignTransactionUseCase
from wallets.infrastructure.account_repository import DjangoAccountRepository
from wallets.infrastructure.transaction_signer_adapter import Secp256k1TransactionSignerAdapter
from wallets.infrastructure.wallet_repository import DjangoWalletRepository


class WalletContainer(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(modules=["wallets.views"])

    # Repositories & Adapters (Singletons)
    wallet_repository = providers.Singleton(DjangoWalletRepository)
    account_repository = providers.Singleton(DjangoAccountRepository)
    transaction_signer = providers.Singleton(Secp256k1TransactionSignerAdapter)

    # Use Cases (Factories)
    sign_transaction_use_case = providers.Factory(
        SignTransactionUseCase,
        transaction_signer=transaction_signer,
    )

    check_balance_use_case = providers.Factory(
        CheckBalanceUseCase,
        account_reader=account_repository,
    )

    create_wallet_use_case = providers.Factory(
        CreateWalletUseCase,
        wallet_writer=wallet_repository,
    )

