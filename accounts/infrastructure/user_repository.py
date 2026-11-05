from typing import Any, Optional
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class DjangoUserRepository:
    """
    Implements UserReader and UserWriter protocols via Django ORM.
    """

    def find_active_by_email(self, email: str) -> Optional[Any]:
        if not email:
            return None
        return User.objects.filter(
            email__iexact=email.strip(),
            is_active=True,
        ).first()

    def find_by_id(self, user_id: str) -> Optional[Any]:
        try:
            return User.objects.filter(id=user_id, is_active=True).first()
        except (ValueError, TypeError):
            return None

    def exists_by_email(self, email: str) -> bool:
        if not email:
            return False
        return User.objects.filter(email__iexact=email.strip()).exists()

    def create_user(
        self,
        *,
        email: str,
        firstName: str,
        lastName: str,
        password: Optional[str] = None,
        is_email_verified: bool = True,
    ) -> Any:
        user = User.objects.create_user(
            email=email.strip().lower(),
            password=password,
            firstName=firstName.strip(),
            lastName=lastName.strip(),
            userType="INDIVIDUAL",
        )
        user.isEmailVerified = is_email_verified
        user.save(update_fields=["isEmailVerified", "userType"])
        return user

    def update_last_login(self, user: Any) -> None:
        if hasattr(user, "last_login"):
            user.last_login = timezone.now()
            user.save(update_fields=["last_login"])
