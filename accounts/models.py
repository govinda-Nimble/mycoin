import uuid

from django.conf import settings
from common.models import BaseModel

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    def create_user(
        self,
        email,
        password=None,
        firstName=None,
        lastName=None,
        **kwargs
    ):
        """
        Create and save a User with the given email and password.
        """
        if not email:
            raise ValueError("The Email must be set")

        email = self.normalize_email(email)

        user = self.model(
            email=email,
            firstName=firstName,
            lastName=lastName,
            **kwargs
        )
        if not password:
            user.set_unusable_password()
        else:
            user.set_password(password)
            
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **kwargs):
        """
        Create and save a SuperUser with the given email and password.
        """

        user = self.create_user(email, password, **kwargs)
        user.is_staff = True
        user.is_superuser = True
        user.save(using=self._db)
        return user


class UserType(models.TextChoices):
    INDIVIDUAL = "INDIVIDUAL", "Individual"
    SYSTEM = "SYSTEM", "System"
    # ORGANIZATION = "ORGANIZATION", "Organization"



class User(AbstractBaseUser, PermissionsMixin):
    USERTYPE = UserType

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    email = models.EmailField(
        unique=True,
        max_length=254,
        error_messages={
            "unique": "A user with this email already exists."
        },
        help_text="User's unique email address."
    )

    firstName = models.CharField(
        max_length=100,
        blank=True,
        help_text="User's first name."
    )
    lastName = models.CharField(
        max_length=100,
        blank=True,
        help_text="User's last name."
    )
    userType = models.CharField(
        max_length=20,
        default='',
        null=True, blank=True,
    )

    isEmailVerified = models.BooleanField(
        default=False,
        help_text="Whether the user's email has been verified."
    )

    is_active = models.BooleanField(
        default=True,
        db_column="isActrive",
    )

    is_staff = models.BooleanField(
        default=False,
        db_column="isStafff"
    )

    dateJoined = models.DateTimeField(
        auto_now_add=True
    )

    updatedAt = models.DateTimeField(
        auto_now=True
    )

    objects = UserManager()

    USERNAME_FIELD = "email"

    REQUIRED_FIELDS = ["firstName", "lastName"]

    class Meta:
        db_table = "accounts_user"
        ordering = ["-dateJoined"]
        indexes = [
            models.Index(
                fields=["is_active"],
                name="user_active_idx"
            ),
            models.Index(
                fields=["userType"],
                name="user_type_idx"
            )
        ]

    def __str__(self):
        return self.email



# class UserProfile(BaseModel):

#     user = models.OneToOneField(
#         settings.AUTH_USER_MODEL,
#         on_delete=models.PROTECT,
#         related_name="profile"
#     )
#     userType = models.CharField(
#         max_length=20,
#         choices=UserType.choices,
#         default=UserType.INDIVIDUAL
#     )
    # dateOfBirth = models.DateField(
    #     null=True,
    #     blank=True
    # )

    # isIdentityVerified = models.BooleanField(default=False)



class OTPTypes(models.TextChoices):
    LOGIN = "LOGIN", "Login"
    REGISTER = "REGISTER", "Register"
    EMAIL_UPDATE = "EMAIL_UPDATE", "Email Update"


class UserOTP(BaseModel):
    OTPTYPES = OTPTypes

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name="userOTPs", 
        null=True, blank=True
    )
    email = models.EmailField(null=True, blank=True)
    otp = models.CharField(
        max_length=128,
        error_messages={
            "required": "OTP is required.",
            "blank": "OTP is required.",
            "max_length": "OTP cannot exceed 128 characters.",
        })
    requestType = models.CharField(
        max_length=30, 
        null=False, blank=False,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    maxAttempts = models.PositiveSmallIntegerField(default=5)
    expiresAt = models.DateTimeField()
    isVerified = models.BooleanField(default=False)
    verifiedAt = models.DateTimeField(null=True, blank=True)
    meta = models.JSONField(default=dict)

    class Meta:
        ordering = ["-createdAt"]

    def __str__(self):
        return f"OTP({self.email} - {self.requestType})"
