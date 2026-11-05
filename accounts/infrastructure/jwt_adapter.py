from typing import Any
from datetime import datetime, timezone as dt_timezone
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken, OutstandingToken
from accounts.domain import UseCaseResult


class DjangoJWTAdapter:
    """
    Implements TokenManager protocol via rest_framework_simplejwt.
    """

    def create_token_pair_for_user(self, user: Any) -> dict[str, Any]:
        user_id = str(user.id)
        
        try:
            OutstandingToken.objects.filter(user_id=user_id).delete()
        except Exception as e:
            logger.warning("Failed to clear previous outstanding tokens for user %s: %s", user_id, exc)
        
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        access_expires_at = datetime.fromtimestamp(
            access["exp"],
            tz=dt_timezone.utc
        )
        refresh_expires_at = datetime.fromtimestamp(
            refresh["exp"],
            tz=dt_timezone.utc
        )

        return {
            "tokenType": "Bearer",
            "accessToken": str(refresh.access_token),
            "refreshToken": str(refresh),
            'accessTokenExpiresAt': access_expires_at,
            'refreshTokenExpiresAt': refresh_expires_at,
        }

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        try:
            token = RefreshToken(refresh_token)
            user_id = token.get('user_id')
            jti = token.get('jti')

            if not user_id:
                return UseCaseResult(
                        success=False,
                        reason="Invalid refresh token.",
                        status_code=400,
                    )
        
            # if not OutstandingToken.objects.filter(
            #     jti=jti,
            #     user_id=user_id,
            #     expires_at__gt=timezone.now(),
            # ).exists():
            #     return UseCaseResult(
            #         success=False,
            #         reason="Invalid or expired refresh token.",
            #         status_code=401,
            #     )

            user = User.objects.get(id=user_id)
            if not user.is_active:
                return UseCaseResult(
                    success=False,
                    reason="User account is not active.",
                    status_code=403,
                )

            return self.create_token_pair_for_user(user=user)
            
        except User.DoesNotExist:
            return UseCaseResult(
                success=False,
                reason="Invalid refresh token.",
                status_code=400,
            )
        except TokenError as exc:
            logger.exception(str(exc))
            return UseCaseResult(
                success=False,
                reason="Invalid or expired refresh token.",
                status_code=401,
            )
        except Exception as exc:
            logger.exception(str(exc))
            return UseCaseResult(
                success=False,
                reason=f"An unexpected error occurred during refresh token: {str(exc)}",
                status_code=500,
            )

    def blacklist_token(self, refresh_token: str) -> bool:
        token = RefreshToken(refresh_token)
        if hasattr(token, "blacklist"):
            token.blacklist()
        return True

