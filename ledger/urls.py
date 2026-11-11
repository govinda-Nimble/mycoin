"""
URL routing for ledger transaction validation and ingestion.
"""

from django.urls import path
from ledger.views import CheckTransactionAPIView
from wallets.views import CheckBalanceAPIView

urlpatterns = [
    path("transactions/validate/", CheckTransactionAPIView.as_view(), name="transaction-validate"),
    path("balance/", CheckBalanceAPIView.as_view(), name="chain-balance"),
    path("balance/<str:address>/", CheckBalanceAPIView.as_view(), name="chain-balance-address"),
]

