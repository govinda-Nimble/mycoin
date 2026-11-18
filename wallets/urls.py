from django.urls import path
from ledger.views import CheckTransactionAPIView, UserTransactionsAPIView
from wallets.views import CheckBalanceAPIView, SignTransactionAPIView

urlpatterns = [
    # Balance endpoints
    path("balance/", CheckBalanceAPIView.as_view(), name="wallet-balance"),
    path("balance/<str:address>/", CheckBalanceAPIView.as_view(), name="wallet-balance-address"),
    
    # Transaction signing endpoint
    path("transactions/sign/", SignTransactionAPIView.as_view(), name="transactions-sign"),
    path("sign-transaction/", SignTransactionAPIView.as_view(), name="sign-transaction"),
    
    # Transaction checking & mempool ingestion aliases
    path("transactions/validate/", CheckTransactionAPIView.as_view(), name="wallet-transactions-validate"),

    # Authenticated user transaction history
    path("transactions/", UserTransactionsAPIView.as_view(), name="wallet-user-transactions"),
    path("transactions/user/", UserTransactionsAPIView.as_view(), name="wallet-transactions-user"),
    path("my-transactions/", UserTransactionsAPIView.as_view(), name="wallet-my-transactions"),
]
