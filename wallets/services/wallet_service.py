"""
Wallet management and cryptographic key generation service.

Generates ECDSA (secp256k1) keypairs and creates Wallet models.
For the centralized prototype, private keys are securely retained in `keyReference`
so the backend can sign future on-chain transactions without a frontend key-manager.
"""

from decimal import Decimal, InvalidOperation
import hashlib
import logging
from typing import Any, Dict, Optional, Tuple, Union

from django.db import transaction
from django.utils import timezone
import ecdsa

from ledger.models import MempoolStatus, MempoolTransaction, TransactionStatus
from network.models import Blockchain, BlockchainStatus
from wallets.models import Account, Wallet, WalletStatus, WalletType

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


def format_coin_amount(amount: int, decimals: int = 8) -> str:
    """Formats an integer amount in smallest units into a human-readable decimal string."""
    dec_val = Decimal(amount) / (Decimal(10) ** decimals)
    return f"{dec_val:.{decimals}f}"


def parse_coin_amount(
    amount_input: Union[str, int, float, Decimal],
    decimals: int = 8,
    is_coin_unit: Optional[bool] = None,
) -> int:
    """
    Parses a coin amount (e.g. '50', '0.5', '0.0005', '0.00000001') or raw base units integer
    into blockchain base units (smallest units).

    Args:
        amount_input: String, int, or Decimal representing the amount.
        decimals: Precision decimals (default: 8).
        is_coin_unit: If True, treats numbers as whole coins (multiplies by 10^decimals).
                      If None (auto-detect), treats numbers with a decimal point (e.g. '0.5')
                      as whole coin units, and pure integer strings as base units.

    Returns:
        int: Amount in smallest base units.
    """
    raw_str = str(amount_input).strip()
    if raw_str.upper().endswith("MYC"):
        raw_str = raw_str[:-3].strip()
        is_coin_unit = True

    try:
        val = Decimal(raw_str)
    except (InvalidOperation, TypeError):
        raise ValueError("Amount must be a valid number.")

    if val <= 0:
        raise ValueError("Amount must be greater than zero.")

    multiplier = Decimal(10 ** decimals)
    min_amount_coin = Decimal("1") / multiplier
    min_amount_str = f"{min_amount_coin:.{decimals}f}"

    if is_coin_unit is None:
        is_coin_unit = "." in raw_str

    if is_coin_unit:
        if val < min_amount_coin:
            raise ValueError(f"Minimum transfer amount is {min_amount_str} MYC (maximum {decimals} decimal places).")

        exponent = val.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -decimals:
            raise ValueError(f"Amount cannot have more than {decimals} decimal places.")

        base_units = val * multiplier
        if base_units % 1 != 0:
            raise ValueError(f"Amount exceeds maximum precision of {decimals} decimals.")
        return int(base_units)
    else:
        if val % 1 != 0:
            raise ValueError("Amount in base units must be an integer.")
        return int(val)


def get_account_balance(
    *,
    user: Optional[Any] = None,
    address: Optional[str] = None,
    chain_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Retrieves the finalized balance, available balance (accounting for active pending mempool txs),
    nonce, and network facts for an authenticated user or target address.

    Returns:
        Dict[str, Any] with camelCase keys.
    """
    # 1. Resolve Blockchain
    if chain_id is not None:
        blockchain = Blockchain.objects.filter(chainId=chain_id).first()
        if not blockchain:
            raise ValueError(f"Blockchain with chain ID {chain_id} does not exist.")
    else:
        blockchain = Blockchain.objects.filter(status=BlockchainStatus.ACTIVE).first()
        if not blockchain:
            raise ValueError("No active blockchain network configured.")

    # 2. Resolve target Address
    target_address = address
    if not target_address:
        if not user or not user.is_authenticated:
            raise ValueError("Authenticated user or address parameter is required.")
        wallet = Wallet.objects.filter(user=user, status=WalletStatus.ACTIVE).first()
        if not wallet:
            raise ValueError("User does not have an active wallet.")
        target_address = wallet.address

    target_address = target_address.strip().lower()

    # 3. Query Account record on the targeted blockchain
    account = Account.objects.filter(blockchain=blockchain, address=target_address).first()

    balance = account.balance if account else 0
    nonce = account.nonce if account else 0
    account_status = account.status if account else "ACTIVE"

    # 4. Check for active pending transactions in the mempool
    now = timezone.now()
    active_mempool_qs = MempoolTransaction.objects.filter(
        status=MempoolStatus.ACTIVE,
        expiresAt__gt=now,
        transaction__status=TransactionStatus.PENDING,
        transaction__block__isnull=True,
        transaction__blockchain=blockchain,
        transaction__sender__address=target_address,
    ).select_related("transaction")

    pending_count = active_mempool_qs.count()
    pending_deductions = 0
    if pending_count > 0:
        for mtx in active_mempool_qs:
            tx = mtx.transaction
            fee = tx.gasLimit * tx.gasPrice
            pending_deductions += (tx.amount + fee)

    available_balance = max(0, balance - pending_deductions)

    return {
        "address": target_address,
        "balance": balance,
        "balanceFormatted": format_coin_amount(balance, blockchain.decimals),
        "availableBalance": available_balance,
        "availableBalanceFormatted": format_coin_amount(available_balance, blockchain.decimals),
        "pendingTransactionsCount": pending_count,
        "symbol": blockchain.symbol,
        "decimals": blockchain.decimals,
        "nonce": nonce,
        "chainId": blockchain.chainId,
        "networkName": blockchain.name,
        "status": account_status,
    }

