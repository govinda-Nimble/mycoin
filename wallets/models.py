"""Wallet (key container, off-chain)
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.conf import settings

from common.models import BaseModel, address_validator, amount_field, check, hex_validator
# Re-export for backward compatibility
# from network.models import Account, AccountType, SystemAccountType, AccountStatus  # noqa: E402, F401


class WalletType(models.TextChoices):
    EXTERNAL = "EXTERNAL", "External (user holds keys; server stores none)"
    KEYSTORE = "KEYSTORE", "Encrypted keystore managed by a key service"


class WalletStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    DISABLED = "DISABLED", "Disabled"
    ARCHIVED = "ARCHIVED", "Archived"


class Wallet(BaseModel):
    """One key pair. Off-chain concept: it is NOT the on-chain balance holder."""

    Type = WalletType
    Status = WalletStatus

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallets",
    )
    name = models.CharField(max_length=100, blank=True)
    walletType = models.CharField(max_length=16, choices=WalletType.choices, default=WalletType.EXTERNAL)
    address = models.CharField(
        max_length=42,
        unique=True,
        validators=[address_validator],
        help_text="Address derived from the public key (0x + 40 hex).",
        error_messages={"unique": "A wallet with this address already exists."},
    )
    publicKey = models.CharField(max_length=130, validators=[hex_validator])
    keyReference = models.CharField(
        max_length=255,
        blank=True,
        help_text="Opaque pointer to the key service. Holds private key in keystore mode.",
    )
    status = models.CharField(max_length=16, choices=WalletStatus.choices, default=WalletStatus.ACTIVE)

    class Meta:
        constraints = [
            check(
                Q(walletType="EXTERNAL") | ~Q(keyReference=""),
                "chain_wallet_keystore_needs_key_reference",
            ),
        ]
        indexes = [models.Index(fields=["status"])]

    @property
    def privateKey(self) -> str:
        """Returns the private key hex string stored in keyReference for prototype backend signing."""
        return self.keyReference

    def get_signing_key(self):
        """Returns the ecdsa SigningKey instance for backend transaction signing."""
        import ecdsa
        if not self.keyReference:
            raise ValueError(f"Wallet {self.address} has no stored private key.")
        return ecdsa.SigningKey.from_string(bytes.fromhex(self.keyReference), curve=ecdsa.SECP256k1)

    def __str__(self):
        return self.name or self.address


# Re-export for backward compatibility
from chain.models import Account, AccountType, SystemAccountType, AccountStatus  # noqa: E402, F401
