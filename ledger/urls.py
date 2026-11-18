"""
URL routing for ledger transaction validation and ingestion.
"""

from django.urls import path
from ledger.views import (
    BlockListAPIView,
    BlockTransactionsAPIView,
    CheckTransactionAPIView,
    TransactionDetailAPIView,
)
from wallets.views import CheckBalanceAPIView

urlpatterns = [
    path("blocks/", BlockListAPIView.as_view(), name="block-list"),
    path("blocks/<str:block_hash>/transactions/", BlockTransactionsAPIView.as_view(), name="block-transactions"),
    path("blocks/<str:block_hash>/", BlockTransactionsAPIView.as_view(), name="block-detail-transactions"),

    path("transactions/validate/", CheckTransactionAPIView.as_view(), name="transaction-validate"),
    path("transactions/<str:tx_hash>/", TransactionDetailAPIView.as_view(), name="transaction-detail"),
    
    path("balance/", CheckBalanceAPIView.as_view(), name="chain-balance"),
    path("balance/<str:address>/", CheckBalanceAPIView.as_view(), name="chain-balance-address"),
]
