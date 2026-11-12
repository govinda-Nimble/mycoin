from django.urls import path
from network.views import GenesisInitAPIView, NetworkStatusAPIView, NodeListAPIView

urlpatterns = [
    path("status/", NetworkStatusAPIView.as_view(), name="network-status"),
    path("nodes/", NodeListAPIView.as_view(), name="network-nodes"),
    path("genesis/", GenesisInitAPIView.as_view(), name="network-genesis"),
]

