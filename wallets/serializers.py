"""
Serializers for wallet and transaction signing endpoints.
Uses camelCase naming convention for request and response attributes.
"""

import re
from rest_framework import serializers

from wallets.services.wallet_service import parse_coin_amount

ADDRESS_REGEX = re.compile(r"^0x[0-9a-fA-F]{40}$")


class SignTransactionSerializer(serializers.Serializer):
    """
    Validates user input required to sign a native coin transfer transaction.
    Supports transfer amounts in human-readable MYC (e.g. '0.5', '0.0005', '0.00000001', '50.0')
    or raw blockchain base units (e.g. '1000000000').
    """

    amount = serializers.CharField(
        required=True,
        help_text="Transaction transfer amount in MYC (e.g. '0.5', '0.0005', '50') or base units (e.g. '1000000000').",
    )
    unit = serializers.ChoiceField(
        choices=["MYC", "BASE"],
        required=False,
        default=None,
        allow_null=True,
        help_text="Optional unit ('MYC' or 'BASE'). Defaults to auto-detection (decimal amounts are treated as MYC).",
    )
    receiverAddress = serializers.CharField(
        required=True,
        help_text="Recipient's 42-character hex address (0x + 40 hex).",
    )

    def validate(self, attrs):
        amount_raw = attrs.get("amount")
        unit = attrs.get("unit")
        is_coin_unit = True if unit == "MYC" else (False if unit == "BASE" else None)

        try:
            base_units = parse_coin_amount(amount_raw, decimals=8, is_coin_unit=is_coin_unit)
        except ValueError as err:
            raise serializers.ValidationError({"amount": str(err)})

        attrs["amount"] = str(base_units)
        return attrs

    def validate_receiverAddress(self, value):
        addr = str(value).strip()
        if not ADDRESS_REGEX.match(addr):
            raise serializers.ValidationError(
                "receiverAddress: Must be '0x' followed by 40 hexadecimal characters."
            )
        return addr.lower()


class AccountBalanceSerializer(serializers.Serializer):
    """
    Representation serializer for account balance response in camelCase.
    """

    address = serializers.CharField(help_text="42-character account hex address.")
    balance = serializers.IntegerField(help_text="Finalized spendable balance in base units.")
    balanceFormatted = serializers.CharField(help_text="Finalized balance in formatted coin units.")
    availableBalance = serializers.IntegerField(help_text="Available balance after active mempool deductions.")
    availableBalanceFormatted = serializers.CharField(help_text="Available balance in formatted coin units.")
    pendingTransactionsCount = serializers.IntegerField(help_text="Number of pending transactions in mempool.")
    symbol = serializers.CharField(help_text="Native currency symbol (e.g. MYC).")
    decimals = serializers.IntegerField(help_text="Smallest unit decimal precision (e.g. 8).")
    nonce = serializers.IntegerField(help_text="Current sequential nonce.")
    chainId = serializers.IntegerField(help_text="Blockchain network chain ID.")
    networkName = serializers.CharField(help_text="Network display name.")
    status = serializers.CharField(help_text="Account status (e.g. ACTIVE).")

