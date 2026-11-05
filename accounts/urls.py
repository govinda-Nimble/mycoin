from django.urls import path
from accounts.views import (
    ConfirmRegisterOtpAPIView,
    LogoutAPIView,
    RefreshTokenAPIView,
    RegisterAPIView,
    RequestLoginOtpAPIView,
    VerifyLoginOtpAPIView,
)

urlpatterns = [
    # Registration Flow (OTP-based)
    path("register/", RegisterAPIView.as_view(), name="register"),
    path("register/verify-otp/", ConfirmRegisterOtpAPIView.as_view(), name="register-verify-otp"),

    # Login Flow (OTP-based)
    path("login/", RequestLoginOtpAPIView.as_view(), name="login"),
    path("login/verify-otp/", VerifyLoginOtpAPIView.as_view(), name="login-verify-otp"),

    # Session & Token Management
    path("logout/", LogoutAPIView.as_view(), name="logout"),
    path("refresh-token/", RefreshTokenAPIView.as_view(), name="refresh-token"),
]
