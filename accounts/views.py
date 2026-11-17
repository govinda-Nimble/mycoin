from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dependency_injector.wiring import Provide, inject

from accounts.application.confirm_register_otp import ConfirmRegisterOtpUseCase
from accounts.application.login_otp_verification import LoginOtpVerificationUseCase
from accounts.application.refresh_token import RefreshTokenUseCase
from accounts.application.register_account import RegisterAccountUseCase
from accounts.application.request_login_otp import RequestLoginOtpUseCase
from accounts.application.user_logout import UserLogoutUseCase
from accounts.serializers import (
    ConfirmRegisterOtpSerializer,
    LoginOtpVerificationSerializer,
    LogoutSerializer,
    RefreshTokenSerializer,
    RegisterSerializer,
    RequestLoginOtpSerializer,
)
from common.utils import get_client_ip, get_single_error
from config.containers import AuthContainer



class RegisterAPIView(APIView):
    """
    Presentation layer: Initiates user registration and issues registration OTP.
    """

    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    @inject
    def post(
        self,
        request,
        use_case: RegisterAccountUseCase = Provide[AuthContainer.register_account_use_case],
    ):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "reason": get_single_error(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = use_case.execute(
            first_name=serializer.validated_data["firstName"],
            last_name=serializer.validated_data["lastName"],
            email=serializer.validated_data["email"],
            client_ip=get_client_ip(request),
        )

        response_body = {"success": result.success, "reason": result.reason}
        if result.data:
            response_body["data"] = result.data
        return Response(response_body, status=result.status_code)



class ConfirmRegisterOtpAPIView(APIView):
    """
    Presentation layer: Validates registration OTP, creates User model,
    links OTP to user, and returns authentication tokens.
    """

    permission_classes = [AllowAny]
    serializer_class = ConfirmRegisterOtpSerializer

    @inject
    def post(
        self,
        request,
        use_case: ConfirmRegisterOtpUseCase = Provide[AuthContainer.confirm_register_otp_use_case],
    ):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "reason": get_single_error(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = use_case.execute(
            first_name=serializer.validated_data["firstName"],
            last_name=serializer.validated_data["lastName"],
            email=serializer.validated_data["email"],
            otp=serializer.validated_data["otp"],
            client_ip=get_client_ip(request),
        )

        response_body = {"success": result.success, "reason": result.reason}
        if result.data:
            response_body["data"] = result.data
        return Response(response_body, status=result.status_code)



class RequestLoginOtpAPIView(APIView):
    """
    Presentation layer: Initiates login by sending an OTP to the user's registered email.
    """

    permission_classes = [AllowAny]
    serializer_class = RequestLoginOtpSerializer

    @inject
    def post(
        self,
        request,
        use_case: RequestLoginOtpUseCase = Provide[AuthContainer.request_login_otp_use_case],
    ):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "reason": get_single_error(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = use_case.execute(
            email=serializer.validated_data["email"],
            client_ip=get_client_ip(request),
        )

        response_body = {"success": result.success, "reason": result.reason}
        if result.data:
            response_body["data"] = result.data
        return Response(response_body, status=result.status_code)



class VerifyLoginOtpAPIView(APIView):
    """
    Presentation layer: Validates login OTP and issues authentication tokens.
    """

    permission_classes = [AllowAny]
    serializer_class = LoginOtpVerificationSerializer

    @inject
    def post(
        self,
        request,
        use_case: LoginOtpVerificationUseCase = Provide[AuthContainer.login_otp_verification_use_case],
    ):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "reason": get_single_error(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = use_case.execute(
            email=serializer.validated_data["email"],
            otp=serializer.validated_data["otp"],
            client_ip=get_client_ip(request),
        )

        response_body = {"success": result.success, "reason": result.reason}
        if result.data:
            response_body["data"] = result.data
        return Response(response_body, status=result.status_code)



class LogoutAPIView(APIView):
    """
    Presentation layer: Revokes active refresh token.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    @inject
    def post(
        self,
        request,
        use_case: UserLogoutUseCase = Provide[AuthContainer.logout_use_case],
    ):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "reason": get_single_error(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user_id = str(request.user.id) if request.user and request.user.is_authenticated else None
        result = use_case.execute(
            refresh_token=serializer.validated_data["refreshToken"],
            user_id=user_id,
            client_ip=get_client_ip(request),
        )

        response_body = {"success": result.success, "reason": result.reason}
        if result.data:
            response_body["data"] = result.data
        return Response(response_body, status=result.status_code)



class RefreshTokenAPIView(APIView):
    """
    Presentation layer: Generates a new access token from an active refresh token.
    """

    permission_classes = [AllowAny]
    serializer_class = RefreshTokenSerializer

    @inject
    def post(
        self,
        request,
        use_case: RefreshTokenUseCase = Provide[AuthContainer.refresh_token_use_case],
    ):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "reason": get_single_error(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = use_case.execute(
            refresh_token=serializer.validated_data["refreshToken"],
            client_ip=get_client_ip(request),
        )

        response_body = {"success": result.success, "reason": result.reason}
        if result.data:
            response_body["data"] = result.data
        return Response(response_body, status=result.status_code)
