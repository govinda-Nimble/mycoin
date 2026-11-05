"""Wallet (key container, off-chain) and Account (on-chain state) models.

No private key is ever stored here. ``Wallet.key_reference`` is only an opaque pointer to an
external key-management component, designed in a later phase.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .base import BaseModel, address_validator, amount_field, check, hex_validator


class WalletType(models.TextChoices):
    EXTERNAL = "EXTERNAL", "External (user holds keys; server stores none)"
    KEYSTORE = "KEYSTORE", "Encrypted keystore managed by a key service"


class WalletStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    DISABLED = "DISABLED", "Disabled"
    ARCHIVED = "ARCHIVED", "Archived"


class AccountType(models.TextChoices):
    EOA = "EOA", "Externally owned account"
    CONTRACT = "CONTRACT", "Contract account"


class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    FROZEN = "FROZEN", "Frozen"
    CLOSED = "CLOSED", "Closed"


class Wallet(BaseModel):
    """One key pair. Off-chain concept: it is NOT the on-chain balance holder."""

    Type = WalletType
    Status = WalletStatus

    name = models.CharField(max_length=100, blank=True)
    wallet_type = models.CharField(max_length=16, choices=WalletType.choices, default=WalletType.EXTERNAL)
    address = models.CharField(
        max_length=42,
        unique=True,
        validators=[address_validator],
        help_text="Address derived from the public key (0x + 40 hex).",
        error_messages={"unique": "A wallet with this address already exists."},
    )
    public_key = models.CharField(max_length=130, validators=[hex_validator])
    key_reference = models.CharField(
        max_length=255,
        blank=True,
        help_text="Opaque pointer to the key service. Never a private key or mnemonic.",
    )
    status = models.CharField(max_length=16, choices=WalletStatus.choices, default=WalletStatus.ACTIVE)

    class Meta:
        constraints = [
            check(
                Q(wallet_type="EXTERNAL") | ~Q(key_reference=""),
                "chain_wallet_keystore_needs_key_reference",
            ),
        ]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return self.name or self.address


class Account(BaseModel):
    """On-chain account state. Balance and nonce change ONLY when a block is finalized."""

    Type = AccountType
    Status = AccountStatus

    blockchain = models.ForeignKey("chain.Blockchain", on_delete=models.PROTECT, related_name="accounts")
    wallet = models.ForeignKey(
        Wallet,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accounts",
        help_text="Managing wallet. Null for contract/system accounts.",
    )
    derivation_index = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Reserved for HD wallets. Null means the account address equals the wallet address.",
    )
    address = models.CharField(
        max_length=42,
        validators=[address_validator],
        error_messages={"unique": "This address already exists on this blockchain."},
    )
    account_type = models.CharField(max_length=16, choices=AccountType.choices, default=AccountType.EOA)
    balance = amount_field("Finalized spendable balance in smallest units.", default=0)
    nonce = models.BigIntegerField(
        default=0,
        help_text="Next expected finalized transaction nonce (sequential, starts at 0).",
    )
    status = models.CharField(max_length=16, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    creation_block = models.ForeignKey(
        "chain.Block",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_accounts",
        help_text="Block that created the account. Null only for genesis accounts.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blockchain", "address"], name="chain_account_unique_address"),
            models.UniqueConstraint(
                fields=["blockchain", "wallet"],
                condition=Q(wallet__isnull=False, derivation_index__isnull=True),
                name="chain_account_one_per_wallet_per_chain",
            ),
            models.UniqueConstraint(
                fields=["blockchain", "wallet", "derivation_index"],
                condition=Q(derivation_index__isnull=False),
                name="chain_account_unique_derivation",
            ),
            check(Q(balance__gte=0), "chain_account_balance_non_negative"),
            check(Q(nonce__gte=0), "chain_account_nonce_non_negative"),
            check(
                Q(account_type="EOA") | Q(wallet__isnull=True),
                "chain_account_contract_has_no_wallet",
            ),
            check(
                Q(derivation_index__isnull=True) | Q(wallet__isnull=False),
                "chain_account_derivation_needs_wallet",
            ),
        ]
        indexes = [models.Index(fields=["blockchain", "status"])]

    def __str__(self):
        return self.address

    def clean(self):
        super().clean()
        if self.wallet_id and self.derivation_index is None and self.address != self.wallet.address:
            raise ValidationError(
                {"address": "Without a derivation index the account address must equal the wallet address."}
            )
