from django.urls import path
from wallets.views import SignTransactionAPIView

urlpatterns = [
    # Transaction signing endpoint
    path("transactions/sign/", SignTransactionAPIView.as_view(), name="transactions-sign"),
]

