"""
URL routing for ledger transaction validation and ingestion.
"""

from django.urls import path
from ledger.views import CheckTransactionAPIView, TransactionDetailAPIView
from wallets.views import CheckBalanceAPIView

urlpatterns = [
    path("transactions/validate/", CheckTransactionAPIView.as_view(), name="transaction-validate"),
    # path("transactions/check/", CheckTransactionAPIView.as_view(), name="transaction-check"),
    path("transactions/<str:tx_hash>/", TransactionDetailAPIView.as_view(), name="transaction-detail"),
    
    path("balance/", CheckBalanceAPIView.as_view(), name="chain-balance"),
    path("balance/<str:address>/", CheckBalanceAPIView.as_view(), name="chain-balance-address"),
]
