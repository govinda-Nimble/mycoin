from django.urls import path
from ledger.views import CheckTransactionAPIView
from wallets.views import CheckBalanceAPIView, SignTransactionAPIView

urlpatterns = [
    # Balance endpoints
    path("balance/", CheckBalanceAPIView.as_view(), name="wallet-balance"),
    path("balance/<str:address>/", CheckBalanceAPIView.as_view(), name="wallet-balance-address"),
    # Transaction signing endpoint
    path("transactions/sign/", SignTransactionAPIView.as_view(), name="transactions-sign"),
    # Transaction checking & mempool ingestion aliases
    path("transactions/validate/", CheckTransactionAPIView.as_view(), name="wallet-transactions-validate"),
]
