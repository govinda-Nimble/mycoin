"""
Domain-specific exceptions for authentication and account management.
These exceptions represent domain rule violations and are decoupled from HTTP or frameworks.
"""


class DomainException(Exception):
    """Base exception for all domain-level errors."""

    default_message = "A domain error occurred."
    default_code = "domain_error"

    def __init__(self, message: str = None, code: str = None):
        self.message = message or self.default_message
        self.code = code or self.default_code
        super().__init__(self.message)


class AuthenticationFailedException(DomainException):
    """Raised when user credentials (e.g., email or password) are invalid."""

    default_message = "Invalid email or password."
    default_code = "authentication_failed"


class UserInactiveException(DomainException):
    """Raised when an inactive or disabled user attempts to authenticate."""

    default_message = "This user account is inactive."
    default_code = "user_inactive"


class UserNotFoundException(DomainException):
    """Raised when a requested user entity does not exist."""

    default_message = "User not found."
    default_code = "user_not_found"


class InvalidTokenException(DomainException):
    """Raised when a provided token is malformed, expired, or invalid."""

    default_message = "The provided token is invalid or expired."
    default_code = "invalid_token"


class TokenRevokedException(DomainException):
    """Raised when an attempt is made to use an already revoked / blacklisted token."""

    default_message = "The token has already been revoked."
    default_code = "token_revoked"

