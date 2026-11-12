from rest_framework import serializers


class RegisterSerializer(serializers.Serializer):
    """Validates registration request payload."""

    firstName = serializers.CharField(
        max_length=100,
        required=True,
        error_messages={"required": "First name is required."}
    )
    lastName = serializers.CharField(
        max_length=100,
        required=True,
        error_messages={"required": "Last name is required."}
    )
    email = serializers.EmailField(
        required=True,
        error_messages={"required": "Email address is required."}
    )


class ConfirmRegisterOtpSerializer(serializers.Serializer):
    """Validates registration OTP confirmation payload."""

    firstName = serializers.CharField(
        max_length=100,
        required=True,
        error_messages={"required": "First name is required."}
    )
    lastName = serializers.CharField(
        max_length=100,
        required=True,
        error_messages={"required": "Last name is required."}
    )
    email = serializers.EmailField(
        required=True,
        error_messages={"required": "Email address is required."}
    )
    otp = serializers.CharField(
        max_length=6,
        min_length=6,
        required=True,
        error_messages={
            "required": "OTP is required.",
            "max_length": "OTP must be exactly 6 digits.",
            "min_length": "OTP must be exactly 6 digits.",
        }
    )


class RequestLoginOtpSerializer(serializers.Serializer):
    """Validates login OTP request payload."""

    email = serializers.EmailField(
        required=True,
        error_messages={"required": "Email address is required."}
    )


class LoginOtpVerificationSerializer(serializers.Serializer):
    """Validates login OTP verification payload."""

    email = serializers.EmailField(
        required=True,
        error_messages={"required": "Email address is required."}
    )
    otp = serializers.CharField(
        max_length=6,
        min_length=6,
        required=True,
        error_messages={
            "required": "OTP is required.",
            "max_length": "OTP must be exactly 6 digits.",
            "min_length": "OTP must be exactly 6 digits.",
        }
    )


class LoginSerializer(serializers.Serializer):
    """Validates password-based login credentials (kept for backward compatibility)."""

    email = serializers.EmailField(
        required=True,
        error_messages={"required": "Email address is required."}
    )
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"},
        error_messages={"required": "Password is required."}
    )


class LogoutSerializer(serializers.Serializer):
    """Validates logout payload. Supports both 'refresh' and 'refreshToken' (camelCase)."""

    refresh = serializers.CharField(
        required=False,
    )

    def validate(self, attrs):
        token = attrs.get("refresh")
        if not token or not str(token).strip():
            raise serializers.ValidationError("Refresh token is required to log out.")
        attrs["refresh"] = str(token).strip()
        return attrs


class RefreshTokenSerializer(serializers.Serializer):
    """Validates refresh token payload. Supports both 'refresh' and 'refreshToken' (camelCase)."""

    refresh = serializers.CharField(
        required=False,
    )
    refreshToken = serializers.CharField(
        required=False,
    )

    def validate(self, attrs):
        token = attrs.get("refresh") or attrs.get("refreshToken")
        if not token or not str(token).strip():
            raise serializers.ValidationError("Refresh token is required.")
        attrs["refresh"] = str(token).strip()
        return attrs
