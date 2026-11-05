"""
Central Dependency Injection Container for mycoin.
Assembles repositories, adapters, and use case factories.
"""

from dependency_injector import containers, providers

from accounts.application.confirm_register_otp import ConfirmRegisterOtpUseCase
from accounts.application.login_otp_verification import LoginOtpVerificationUseCase
from accounts.application.refresh_token import RefreshTokenUseCase
from accounts.application.register_account import RegisterAccountUseCase
from accounts.application.request_login_otp import RequestLoginOtpUseCase
from accounts.application.user_login import UserLoginUseCase
from accounts.application.user_logout import UserLogoutUseCase
from accounts.infrastructure.activity import DjangoActivityRecorder
from accounts.infrastructure.jwt_adapter import DjangoJWTAdapter
from accounts.infrastructure.otp_repository import DjangoOTPRepository
from accounts.infrastructure.user_repository import DjangoUserRepository
from accounts.infrastructure.wallet_adapter import DjangoWalletAdapter


class AuthContainer(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(modules=["accounts.views"])

    # 1. Repositories & Adapters (Singletons)
    user_repository = providers.Singleton(DjangoUserRepository)
    otp_repository = providers.Singleton(DjangoOTPRepository)
    jwt_adapter = providers.Singleton(DjangoJWTAdapter)
    activity_recorder = providers.Singleton(DjangoActivityRecorder)
    wallet_adapter = providers.Singleton(DjangoWalletAdapter)

    # 2. Use Cases (Factories create a fresh instance per request)
    register_account_use_case = providers.Factory(
        RegisterAccountUseCase,
        user_reader=user_repository,
        otp_manager=otp_repository,
        activity_recorder=activity_recorder,
    )

    confirm_register_otp_use_case = providers.Factory(
        ConfirmRegisterOtpUseCase,
        user_reader=user_repository,
        user_writer=user_repository,
        otp_manager=otp_repository,
        token_manager=jwt_adapter,
        activity_recorder=activity_recorder,
        wallet_creator=wallet_adapter,
    )

    request_login_otp_use_case = providers.Factory(
        RequestLoginOtpUseCase,
        user_reader=user_repository,
        otp_manager=otp_repository,
        activity_recorder=activity_recorder,
    )

    login_otp_verification_use_case = providers.Factory(
        LoginOtpVerificationUseCase,
        user_reader=user_repository,
        user_writer=user_repository,
        otp_manager=otp_repository,
        token_manager=jwt_adapter,
        activity_recorder=activity_recorder,
    )

    login_use_case = providers.Factory(
        UserLoginUseCase,
        user_reader=user_repository,
        user_writer=user_repository,
        token_manager=jwt_adapter,
        activity_recorder=activity_recorder,
    )

    logout_use_case = providers.Factory(
        UserLogoutUseCase,
        token_manager=jwt_adapter,
        activity_recorder=activity_recorder,
    )

    refresh_token_use_case = providers.Factory(
        RefreshTokenUseCase,
        token_manager=jwt_adapter,
        activity_recorder=activity_recorder,
    )


container = AuthContainer()
