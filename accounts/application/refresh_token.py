import logging
from typing import Optional

from accounts.domain import ActivityRecorder, TokenManager, UseCaseResult

logger = logging.getLogger(__name__)


class RefreshTokenUseCase:
    """
    Orchestrates JWT access token renewal using an active refresh token.
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
        client_ip: Optional[str] = None,
    ) -> UseCaseResult:
        try:
            token_data = self._tokens.refresh_access_token(refresh_token)
        except Exception as exc:
            logger.warning("Token renewal failed: %s", exc)
            return UseCaseResult(
                success=False,
                reason="The refresh token is invalid or expired.",
                status_code=401,
            )

        self._activity.record_token_refreshed(ip_address=client_ip)

        return UseCaseResult(
            success=True,
            reason="Token refreshed successfully.",
            status_code=200,
            data={"tokens": token_data},
        )

