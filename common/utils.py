import re
from typing import Any, Union
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError as DjangoValidationError

from common.models import ImmutableRecordError

CONSTRAINT_MESSAGES = {
    # Ledger Transactions
    "chain_tx_amount_positive": "Transaction amount must be greater than zero.",
    "chain_tx_gas_limit_positive": "Gas limit must be greater than zero.",
    "chain_tx_nonce_non_negative": "Transaction nonce cannot be negative.",
    "chain_tx_gas_price_non_negative": "Gas price cannot be negative.",
    "chain_tx_fee_within_gas_limit": "Gas used cannot exceed the transaction gas limit.",
    "chain_tx_fee_only_when_executed": "Transaction fee can only be applied to executed transactions.",
    "chain_tx_block_matches_status": "Block association must match transaction execution status.",
    "chain_tx_signature_required": "Transaction signature is required.",
    "chain_tx_public_key_with_signature": "Sender public key is required for signed transactions.",
    "ledger_transaction_hash_key": "A transaction with this hash already exists on the ledger.",
    "chain_tx_unique_hash": "A transaction with this hash already exists on the ledger.",

    # Ledger Blocks
    "chain_block_unique_hash": "A block with this hash already exists on the blockchain.",
    "chain_block_unique_finalized_height": "A block at this finalized height already exists on the blockchain.",
    "chain_block_genesis_rule": "Block violates genesis or parent block structure rules.",
    "chain_block_finalized_has_timestamp": "Finalized blocks must include a finalization timestamp.",
    "chain_block_amounts_non_negative": "Block rewards and gas amounts cannot be negative.",
    "chain_blocktx_unique_index": "Duplicate transaction index within the block.",

    # Mempool & Receipts & Events
    "chain_mempool_unique_node_tx": "This transaction is already active in the node's mempool.",
    "chain_receipt_amounts_non_negative": "Receipt gas used and fee amounts cannot be negative.",
    "chain_txevent_unique_index": "Duplicate event index within the transaction receipt.",

    # Network / Nodes / Accounts
    "chain_account_unique_address": "An on-chain account with this address already exists on the blockchain.",
    "chain_node_unique_endpoint": "A node with this endpoint already exists in the network.",
    "chain_nodepeer_unique_pair": "A peer connection between these nodes already exists.",
    "network_node_nodeId_key": "A node with this node ID already exists.",
    "chain_vote_one_per_validator": "Validator has already cast a vote for this block.",
    "chain_reward_unique_per_block_type": "A reward of this type has already been granted for this block.",
    "chain_slash_unique_evidence": "Slashing evidence has already been submitted for this validator.",

    # Accounts & Wallets
    "accounts_user_email_key": "An account with this email address already exists.",
    "wallets_wallet_address_key": "A wallet with this address already exists.",
    "wallets_wallet_publicKey_key": "A wallet with this public key already exists.",
    "chain_wallet_keystore_needs_key_reference": "Keystore wallets require a valid key reference.",
}


def format_database_constraint_error(exc: Exception) -> str:
    """
    Translates raw database constraint exceptions (PostgreSQL/SQLite IntegrityError,
    Django ValidationError, ImmutableRecordError) into human-readable, safe error messages
    suitable for frontend display without leaking database internals.
    """
    if isinstance(exc, ImmutableRecordError):
        return "This record is finalized and cannot be modified or deleted."

    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            return get_single_error(exc.message_dict)
        if hasattr(exc, "messages") and exc.messages:
            return get_single_error(exc.messages)
        return str(exc)

    err_str = str(exc)

    # 1. Check known named constraints in message
    for name, friendly_msg in CONSTRAINT_MESSAGES.items():
        if name in err_str:
            return friendly_msg

    # 2. Extract constraint name via regex from Postgres syntax:
    # "violates unique/check/foreign key constraint \"xyz\""
    constraint_match = re.search(
        r'violates\s+(?:unique|check|foreign\s+key|not-null)?\s*constraint\s*["\']?(\w+)["\']?',
        err_str,
        re.IGNORECASE,
    )
    if constraint_match:
        c_name = constraint_match.group(1)
        if c_name in CONSTRAINT_MESSAGES:
            return CONSTRAINT_MESSAGES[c_name]

    # 3. Postgres detail extraction for unique violations:
    # DETAIL: Key (column_name)=(val) already exists.
    unique_detail = re.search(r"Key\s+\((.*?)\)=\(.*?\)\s+already exists", err_str, re.IGNORECASE)
    if unique_detail:
        fields = unique_detail.group(1).replace("_", " ")
        return f"A record with this {fields} already exists."

    # 4. Check constraint violation generic fallback
    if "violates check constraint" in err_str or "CHECK constraint failed" in err_str:
        return "Record violates database validation rules."

    # 5. Not-null violation
    not_null_match = re.search(
        r'null value in column ["\']?(\w+)["\']?.*violates not-null constraint',
        err_str,
        re.IGNORECASE,
    )
    if not_null_match:
        col = not_null_match.group(1).replace("_", " ")
        return f"Field '{col}' is required and cannot be empty."

    # 6. SQLite format unique violation:
    # UNIQUE constraint failed: table.field
    sqlite_unique = re.search(r"UNIQUE constraint failed:\s*([\w\.]+)", err_str, re.IGNORECASE)
    if sqlite_unique:
        field = sqlite_unique.group(1).split(".")[-1].replace("_", " ")
        return f"A record with this {field} already exists."

    # 7. Foreign key violation generic
    if "violates foreign key constraint" in err_str or "FOREIGN KEY constraint failed" in err_str:
        return "Referenced resource does not exist or cannot be modified."

    return "A database integrity constraint was violated."



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

