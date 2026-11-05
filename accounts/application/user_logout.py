from typing import Optional
from accounts.domain import ActivityRecorder, TokenManager, UseCaseResult


class UserLogoutUseCase:
    """
    Orchestrates user session termination and token revocation.
    """

    def __init__(
        self,
        token_manager: TokenManager,
        activity_recorder: ActivityRecorder,
    ):
        self._tokens = token_manager
        self._activity = activity_recorder

    def execute(
        self,
        *,
        refresh_token: str,
        user_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> UseCaseResult:
        try:
            self._tokens.blacklist_token(refresh_token)
        except Exception:
            return UseCaseResult(
                success=False,
                reason="The refresh token is invalid or has already been revoked.",
                status_code=400,
            )

        self._activity.record_logout(user_id=user_id, ip_address=client_ip)

        return UseCaseResult(
            success=True,
            reason="Logged out successfully.",
            status_code=200,
        )

