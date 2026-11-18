"""
URL routing for ledger transaction validation and ingestion.
"""

from django.urls import path
from ledger.views import (
    BlockListAPIView,
    BlockTransactionsAPIView,
    CheckTransactionAPIView,
    TransactionDetailAPIView,
    UserTransactionsAPIView,
)
from wallets.views import CheckBalanceAPIView

urlpatterns = [
    path("blocks/", BlockListAPIView.as_view(), name="block-list"),
    path("blocks/<str:block_hash>/transactions/", BlockTransactionsAPIView.as_view(), name="block-transactions"),
    path("blocks/<str:block_hash>/", BlockTransactionsAPIView.as_view(), name="block-detail-transactions"),

    path("transactions/validate/", CheckTransactionAPIView.as_view(), name="transaction-validate"),
    
    path("transactions/<str:tx_hash>/", TransactionDetailAPIView.as_view(), name="transaction-detail"),

    path("transactions/", UserTransactionsAPIView.as_view(), name="user-transactions"),
    path("transactions/user/", UserTransactionsAPIView.as_view(), name="user-transactions-alt"),
    path("my-transactions/", UserTransactionsAPIView.as_view(), name="my-transactions"),
    
    path("balance/", CheckBalanceAPIView.as_view(), name="chain-balance"),
    path("balance/<str:address>/", CheckBalanceAPIView.as_view(), name="chain-balance-address"),
]
