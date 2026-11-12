from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class RefreshTokenAPITests(TestCase):
    """
    Tests for RefreshTokenAPIView ensuring tokens can be renewed
    using both 'refresh' and 'refreshToken' (camelCase).
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="refresh_tester@example.com",
            firstName="Token",
            lastName="Tester",
            userType="INDIVIDUAL",
        )
        self.refresh_url = reverse("refresh-token")

    def test_refresh_token_success_with_refresh_field(self):
        """Test refreshing access token using standard 'refresh' payload key."""
        token = RefreshToken.for_user(self.user)
        refresh_str = str(token)

        response = self.client.post(self.refresh_url, {"refresh": refresh_str}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["reason"], "Token refreshed successfully.")
        tokens = response.data["data"]["tokens"]
        self.assertIn("accessToken", tokens)
        self.assertIn("refreshToken", tokens)
        self.assertEqual(tokens["tokenType"], "Bearer")

    def test_refresh_token_success_with_camelcase_refreshtoken_field(self):
        """Test refreshing access token using camelCase 'refreshToken' payload key."""
        token = RefreshToken.for_user(self.user)
        refresh_str = str(token)

        response = self.client.post(self.refresh_url, {"refreshToken": refresh_str}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["reason"], "Token refreshed successfully.")
        tokens = response.data["data"]["tokens"]
        self.assertIn("accessToken", tokens)
        self.assertIn("refreshToken", tokens)

    def test_refresh_token_invalid_returns_401(self):
        """Test invalid refresh token string returns 401 Unauthorized."""
        response = self.client.post(self.refresh_url, {"refresh": "invalid.jwt.token"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["reason"], "The refresh token is invalid or expired.")

    def test_refresh_token_missing_payload_returns_400(self):
        """Test missing refresh token in payload returns 400 Bad Request."""
        response = self.client.post(self.refresh_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("Refresh token is required", response.data["reason"])

    def test_refresh_token_inactive_user_returns_401(self):
        """Test refresh token for an inactive user returns 401."""
        self.user.is_active = False
        self.user.save()

        token = RefreshToken.for_user(self.user)
        response = self.client.post(self.refresh_url, {"refresh": str(token)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["reason"], "The refresh token is invalid or expired.")
