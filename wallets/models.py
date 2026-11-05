"""Wallet (key container, off-chain) and Account (on-chain state) models.

No private key is ever stored here. ``Wallet.key_reference`` is only an opaque pointer to an
external key-management component, designed in a later phase.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.conf import settings

from common.models import BaseModel, address_validator, amount_field, check, hex_validator


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


class SystemAccountType(models.TextChoices):
    TREASURY = "TREASURY", "Treasury"
    VALIDATOR_RESERVE = "VALIDATOR_RESERVE", "Validator Reserve"
    DEVELOPMENT_RESERVE = "DEVELOPMENT_RESERVE", "Development Reserve"

    
class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    FROZEN = "FROZEN", "Frozen"
    CLOSED = "CLOSED", "Closed"


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



class Account(BaseModel):
    """On-chain account state. Balance and nonce change ONLY when a block is finalized."""

    Type = AccountType
    Status = AccountStatus

    blockchain = models.ForeignKey("network.Blockchain", on_delete=models.PROTECT, related_name="accounts")
    systemAccountType = models.CharField(
        max_length=30,
        choices=SystemAccountType.choices,
        null=True,
        blank=True,
        help_text="Identifies the purpose of a system account."
    )
    wallet = models.ForeignKey(
        Wallet,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accounts",
        help_text="Managing wallet. Null for contract/system accounts.",
    )
    derivationIndex = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Reserved for HD wallets. Null means the account address equals the wallet address.",
    )
    address = models.CharField(
        max_length=42,
        validators=[address_validator],
        error_messages={"unique": "This address already exists on this blockchain."},
    )
    accountType = models.CharField(max_length=16, choices=AccountType.choices, default=AccountType.EOA)
    balance = amount_field("Finalized spendable balance in smallest units.", default=0)
    nonce = models.BigIntegerField(
        default=0,
        help_text="Next expected finalized transaction nonce (sequential, starts at 0).",
    )
    status = models.CharField(max_length=16, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    creationBlock = models.ForeignKey(
        "ledger.Block",
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
                condition=Q(wallet__isnull=False, derivationIndex__isnull=True),
                name="chain_account_one_per_wallet_per_chain",
            ),
            models.UniqueConstraint(
                fields=["blockchain", "wallet", "derivationIndex"],
                condition=Q(derivationIndex__isnull=False),
                name="chain_account_unique_derivation",
            ),
            check(Q(balance__gte=0), "chain_account_balance_non_negative"),
            check(Q(nonce__gte=0), "chain_account_nonce_non_negative"),
            check(
                Q(accountType="EOA") | Q(wallet__isnull=True),
                "chain_account_contract_has_no_wallet",
            ),
            check(
                Q(derivationIndex__isnull=True) | Q(wallet__isnull=False),
                "chain_account_derivation_needs_wallet",
            ),
        ]
        indexes = [models.Index(fields=["blockchain", "status"])]

    def __str__(self):
        return self.address

    def clean(self):
        super().clean()
        if self.wallet_id and self.derivationIndex is None and self.address != self.wallet.address:
            raise ValidationError(
                {"address": "Without a derivation index the account address must equal the wallet address."}
            )
