"""
Serializers for wallet and transaction signing endpoints.
Uses camelCase naming convention for request and response attributes.
"""

import re
from rest_framework import serializers

ADDRESS_REGEX = re.compile(r"^0x[0-9a-fA-F]{40}$")


class SignTransactionSerializer(serializers.Serializer):
    """
    Validates user input required to sign a native coin transfer transaction.
    User sends only amount and receiverAddress.
    """

    amount = serializers.CharField(
        required=True,
        help_text="Transaction transfer amount in smallest units (positive integer string).",
    )
    receiverAddress = serializers.CharField(
        required=True,
        help_text="Recipient's 42-character hex address (0x + 40 hex).",
    )

    def validate_amount(self, value):
        val_str = str(value).strip()
        try:
            val_int = int(val_str)
        except ValueError:
            raise serializers.ValidationError("Amount must be a valid integer in smallest units.")
        if val_int <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return str(val_int)

    def validate_receiverAddress(self, value):
        addr = str(value).strip()
        if not ADDRESS_REGEX.match(addr):
            raise serializers.ValidationError(
                "Must be '0x' followed by 40 hexadecimal characters."
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

