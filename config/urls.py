from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/wallets/", include("wallets.urls")),
    path("api/ledger/", include("ledger.urls")),
    path("api/transactions/", include("ledger.urls")),
    path("api/network/", include("network.urls")),
    path("api/chain/", include("chain.urls")),
    path("api/staking/", include("staking.urls")),
    path("api/", include("ledger.urls")),
]
