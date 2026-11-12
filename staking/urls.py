from django.urls import path
from staking.views import ValidatorDetailAPIView, ValidatorListAPIView

urlpatterns = [
    path("validators/", ValidatorListAPIView.as_view(), name="staking-validators"),
    path("validators/<str:validator_id>/", ValidatorDetailAPIView.as_view(), name="staking-validator-detail"),
]

