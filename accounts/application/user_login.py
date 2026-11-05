from typing import Optional
from accounts.domain import (
    ActivityRecorder,
    TokenManager,
    UseCaseResult,
    UserReader,
    UserWriter,
)


class UserLoginUseCase:
    """
    Orchestrates user authentication and JWT token creation.
    """

    def __init__(
        self,
        user_reader: UserReader,
        user_writer: UserWriter,
        token_manager: TokenManager,
        activity_recorder: ActivityRecorder,
    ):
        self._users = user_reader
        self._user_writer = user_writer
        self._tokens = token_manager
        self._activity = activity_recorder

    def execute(
        self,
        *,
        email: str,
        password: str,
        client_ip: Optional[str] = None,
    ) -> UseCaseResult:
    
        user = self._users.find_active_by_email(email)
        if not user or not user.check_password(password):
            return UseCaseResult(
                success=False,
                reason="Invalid email or password.",
                status_code=401,
            )

        if not getattr(user, "is_active", True):
            return UseCaseResult(
                success=False,
                reason="Your account is inactive. Please contact support.",
                status_code=403,
            )

        # Update last login timestamp
        self._user_writer.update_last_login(user)

        # Generate tokens
        token_data = self._tokens.create_token_pair_for_user(user)

        # Record activity
        self._activity.record_login(user=user, ip_address=client_ip)

        return UseCaseResult(
            success=True,
            reason="Login successful.",
            status_code=200,
            data={
                "tokens": token_data,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "firstName": getattr(user, "firstName", ""),
                    "lastName": getattr(user, "lastName", ""),
                    "isEmailVerified": getattr(user, "is_email_verified", False),
                },
            },
        )

