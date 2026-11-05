"""
Wallet management and cryptographic key generation service.

Generates ECDSA (secp256k1) keypairs and creates Wallet models.
For the centralized prototype, private keys are securely retained in `keyReference`
so the backend can sign future on-chain transactions without a frontend key-manager.
"""

import hashlib
import logging
from typing import Any, Tuple

from django.db import transaction
import ecdsa

from wallets.models import Wallet, WalletStatus, WalletType

logger = logging.getLogger(__name__)


def generate_keypair() -> Tuple[str, str, str]:
    """
    Generate an ECDSA secp256k1 keypair.

    Returns:
        Tuple[str, str, str]: (private_key_hex, public_key_hex, address)
        - private_key_hex: 64 lowercase hex characters (32 bytes).
        - public_key_hex: 130 lowercase hex characters (04 prefix + 64 bytes).
        - address: 42 lowercase hex characters ('0x' + 40 hex chars).
    """
    sk = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1)
    private_key_hex = sk.to_string().hex().lower()

    vk = sk.get_verifying_key()
    public_key_hex = ("04" + vk.to_string().hex()).lower()

    # Derive 0x + 40 hex address from SHA-256 of the public key payload
    address_hash = hashlib.sha256(vk.to_string()).hexdigest().lower()
    address = "0x" + address_hash[-40:]

    return private_key_hex, public_key_hex, address


def create_wallet_for_user(user: Any, name: str = "") -> Wallet:
    """
    Idempotently create an active Wallet for the registered user.
    If the user already has an active wallet, returns it.

    Args:
        user: The User instance for whom the wallet is created.
        name: Optional custom display name for the wallet.

    Returns:
        Wallet: The created or existing Wallet model instance.
    """
    with transaction.atomic():
        existing_wallet = Wallet.objects.filter(user=user, status=WalletStatus.ACTIVE).first()
        if existing_wallet:
            logger.info("User %s already has active wallet %s", user.email, existing_wallet.address)
            return existing_wallet

        # Generate unique address
        while True:
            private_key_hex, public_key_hex, address = generate_keypair()
            if not Wallet.objects.filter(address=address).exists():
                break

        display_name = name.strip() or f"{getattr(user, 'firstName', '') or 'User'}'s Wallet".strip()

        wallet = Wallet(
            user=user,
            name=display_name,
            walletType=WalletType.KEYSTORE,
            address=address,
            publicKey=public_key_hex,
            keyReference=private_key_hex,
            status=WalletStatus.ACTIVE,
        )
        wallet.full_clean()
        wallet.save()

        logger.info("Created wallet %s for user %s", wallet.address, user.email)
        return wallet

