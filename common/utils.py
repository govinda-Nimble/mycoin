from typing import Any, Union
from django.contrib.auth.hashers import check_password, make_password



def get_client_ip(request) -> str:
    """
    Extract client IP address from HTTP request headers or remote address.
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or ""


def get_single_error(errors: Union[dict, list, str, Any]) -> str:
    """
    Recursively extract the first error message string from DRF serializer.errors.
    """
    if isinstance(errors, dict):
        for field, err in errors.items():
            return get_single_error(err)
    elif isinstance(errors, (list, tuple)):
        if errors:
            return get_single_error(errors[0])
        return "Validation failed."
    return str(errors)


def hash_password(raw_password: str) -> str:
    """
    Hash a plaintext password using Django's secure password hashers.
    """
    return make_password(raw_password)

