"""Shared building blocks for every MyCoin ORM model (infrastructure layer)."""
import uuid

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

# Convention: the genesis block's ``previous_hash`` is 64 zeros.
GENESIS_PREVIOUS_HASH = "0" * 64

hash_validator = RegexValidator(
    regex=r"^[0-9a-f]{64}$",
    message="Must be exactly 64 lowercase hexadecimal characters.",
)
address_validator = RegexValidator(
    regex=r"^0x[0-9a-f]{40}$",
    message="Must be '0x' followed by 40 lowercase hexadecimal characters.",
)
hex_validator = RegexValidator(
    regex=r"^[0-9a-f]+$",
    message="Must contain only lowercase hexadecimal characters.",
)


class ImmutableRecordError(Exception):
    """Raised when code tries to change or delete a finalized (immutable) record."""


class BaseModel(models.Model):
    """UUID primary key plus created/updated timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def check(condition, name):
    """CheckConstraint that works on Django 4.2/5.0 (``check=``) and 5.1+ (``condition=``)."""
    try:
        return models.CheckConstraint(condition=condition, name=name)
    except TypeError:  # Django < 5.1
        return models.CheckConstraint(check=condition, name=name)


def amount_field(help_text, **kwargs):
    """Integer smallest-unit amount (never float/Decimal). Non-negative; stricter rules go in constraints."""
    return models.BigIntegerField(
        help_text=help_text, validators=[MinValueValidator(0)], **kwargs
    )
