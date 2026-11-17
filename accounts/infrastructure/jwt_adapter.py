from datetime import datetime, timezone as dt_timezone
import logging
from typing import Any, Dict

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import OutstandingToken, RefreshToken

logger = logging.getLogger(__name__)
User = get_user_model()


class DjangoJWTAdapter:
    """
    Implements TokenManager protocol via rest_framework_simplejwt.
    """

    def create_token_pair_for_user(self, user: Any) -> Dict[str, Any]:
        user_id = str(user.id)
        try:
            # Clear previous non-blacklisted outstanding tokens to prevent token accumulation
            OutstandingToken.objects.filter(user_id=user_id, blacklistedtoken__isnull=True).delete()
        except Exception as exc:
            logger.debug("Failed to clear previous non-blacklisted outstanding tokens for user %s: %s", user_id, exc)

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
            "accessToken": str(access),
            "refreshToken": str(refresh),
            "accessTokenExpiresAt": access_expires_at,
            "refreshTokenExpiresAt": refresh_expires_at,
        }

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Validates the refresh token and generates a fresh token pair.
        Raises TokenError if the token is invalid, expired, blacklisted, or if user is inactive.
        """
        try:
            token = RefreshToken(refresh_token)
        except (TokenError, InvalidToken) as exc:
            logger.warning("Invalid or expired refresh token: %s", exc)
            raise TokenError("The refresh token is invalid or expired.") from exc

        user_id = token.get("user_id") or token.get(api_settings.USER_ID_CLAIM)
        if not user_id:
            logger.warning("Refresh token contains no user identification claim.")
            raise TokenError("The refresh token is invalid or expired.")

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.warning("User %s associated with refresh token does not exist.", user_id)
            raise TokenError("The refresh token is invalid or expired.")

        if not user.is_active:
            logger.warning("User %s associated with refresh token is not active.", user_id)
            raise TokenError("User account is not active.")

        # Issue fresh token pair for the user
        return self.create_token_pair_for_user(user=user)


    def blacklist_token(self, refresh_token: str, user_id: str) -> bool:
        """
        Revokes a refresh token by removing it from the OutstandingToken table.
        Blacklisted tokens are not stored in the database; instead, the token is cleared.
        """
        try:
            token = RefreshToken(refresh_token)
        except (TokenError, InvalidToken) as exc:
            logger.warning("Invalid or expired refresh token: %s", exc)
            raise TokenError("The refresh token is invalid or expired.") from exc

        try:
            if str(user_id) != str(token.get("user_id")):
                logger.warning("User %s associated with refresh token does not exist.", user_id)
                raise TokenError("The refresh token is invalid or expired.")

            jti = token.get(api_settings.JTI_CLAIM) or token.get("jti")
            deleted = 0
            if jti:
                deleted, _ = OutstandingToken.objects.filter(jti=jti).delete()

            if not deleted:
                deleted, _ = OutstandingToken.objects.filter(token=refresh_token).delete()

            if not deleted:
                logger.warning("Token with jti %s not found in outstanding tokens or already revoked.", jti)
                raise TokenError("The refresh token is invalid or has already been revoked.")

            return True
        except TokenError:
            raise
        except Exception as exc:
            logger.error("Failed to remove token from table: %s", exc)
            raise TokenError("Failed to revoke token.") from exc


