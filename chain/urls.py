from django.urls import path
from chain.views import ChainStatusAPIView, GenesisInitAPIView

urlpatterns = [
    path("status/", ChainStatusAPIView.as_view(), name="chain-status"),
    path("genesis/", GenesisInitAPIView.as_view(), name="chain-genesis"),
]

