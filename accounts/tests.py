from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import OTPTypes, UserOTP

User = get_user_model()


class RegisterAPITests(TestCase):
    """Tests for RegisterAPIView (/api/auth/register/)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.url = reverse("register")

    def test_register_success(self):
        payload = {
            "firstName": "John",
            "lastName": "Doe",
            "email": "johndoe@example.com",
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("OTP sent successfully", response.data["reason"])
        self.assertTrue(UserOTP.objects.filter(email="johndoe@example.com").exists())

    def test_register_duplicate_email(self):
        User.objects.create_user(
            email="existing@example.com",
            firstName="Existing",
            lastName="User",
        )
        payload = {
            "firstName": "Existing",
            "lastName": "User",
            "email": "existing@example.com",
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("already exists", response.data["reason"])

    def test_register_missing_fields(self):
        response = self.client.post(self.url, {"email": "bad@test.com"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])


class ConfirmRegisterOtpAPITests(TestCase):
    """Tests for ConfirmRegisterOtpAPIView (/api/auth/register/verify-otp/)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.url = reverse("register-verify-otp")
        self.email = "newuser@example.com"
        # Seed an OTP
        UserOTP.objects.create(
            email=self.email,
            otp="111111",
            requestType=OTPTypes.REGISTER,
            expiresAt=timezone.now() + timedelta(minutes=10),
        )

    def test_confirm_register_otp_success(self):
        payload = {
            "firstName": "Alice",
            "lastName": "Smith",
            "email": self.email,
            "otp": "111111",
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertTrue(User.objects.filter(email=self.email).exists())
        self.assertIn("tokenData", response.data["data"])
        self.assertIn("userData", response.data["data"])

    def test_confirm_register_otp_invalid_code(self):
        payload = {
            "firstName": "Alice",
            "lastName": "Smith",
            "email": self.email,
            "otp": "999999",
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("Invalid OTP", response.data["reason"])

    def test_confirm_register_otp_missing_fields(self):
        response = self.client.post(self.url, {"email": self.email}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])


class LoginOtpAPITests(TestCase):
    """Tests for login OTP flow (/api/auth/login/ and /api/auth/login/verify-otp/)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.login_url = reverse("login")
        self.verify_url = reverse("login-verify-otp")
        self.user = User.objects.create_user(
            email="login_user@example.com",
            firstName="Login",
            lastName="User",
        )

    def test_request_login_otp_success(self):
        response = self.client.post(self.login_url, {"email": self.user.email}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("OTP sent successfully", response.data["reason"])

    def test_request_login_otp_nonexistent_email(self):
        response = self.client.post(self.login_url, {"email": "notfound@example.com"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])

    def test_verify_login_otp_success(self):
        # Request OTP first
        self.client.post(self.login_url, {"email": self.user.email}, format="json")

        # Verify OTP
        payload = {"email": self.user.email, "otp": "111111"}
        response = self.client.post(self.verify_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("tokens", response.data["data"])
        self.assertIn("accessToken", response.data["data"]["tokens"])

    def test_verify_login_otp_invalid_code(self):
        self.client.post(self.login_url, {"email": self.user.email}, format="json")
        payload = {"email": self.user.email, "otp": "000000"}
        response = self.client.post(self.verify_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])


class LogoutAPITests(TestCase):
    """Tests for LogoutAPIView (/api/auth/logout/)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.logout_url = reverse("logout")
        self.user = User.objects.create_user(
            email="logout_user@example.com",
            firstName="Logout",
            lastName="User",
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.access = str(self.refresh.access_token)

    def test_logout_authenticated_success(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        response = self.client.post(self.logout_url, {"refreshToken": str(self.refresh)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["reason"], "User logged out successfully.")

    def test_logout_unauthenticated_returns_401(self):
        response = self.client.post(self.logout_url, {"refreshToken": str(self.refresh)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_missing_token_returns_400(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        response = self.client.post(self.logout_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])


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
