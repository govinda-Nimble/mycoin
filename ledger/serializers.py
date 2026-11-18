"""
Serializers for transaction validation and ingestion.
Uses camelCase attribute names matching the client/wallet contract.
"""

import re
from rest_framework import serializers

ADDRESS_REGEX = re.compile(r"^0x[0-9a-fA-F]{40}$")
HEX_REGEX = re.compile(r"^[0-9a-fA-F]+$")


class CheckTransactionSerializer(serializers.Serializer):
    """
    Validates the structure and basic types of an incoming signed transaction payload.
    Deep cryptographic, balance, nonce, and ledger validation is handled by the domain service.
    """

    senderAddress = serializers.CharField(
        required=True,
        help_text="Sender's 42-character address (0x + 40 hex).",
    )
    receiverAddress = serializers.CharField(
        required=True,
        help_text="Receiver's 42-character address (0x + 40 hex).",
    )
    amount = serializers.CharField(
        required=True,
        help_text="Transfer amount in base units (positive integer string).",
    )
    nonce = serializers.IntegerField(
        required=True,
        min_value=0,
        help_text="Sender's sequential account nonce (>= 0).",
    )
    gasLimit = serializers.IntegerField(
        required=True,
        min_value=1,
        help_text="Maximum gas units allocated for this transaction.",
    )
    gasPrice = serializers.CharField(
        required=True,
        help_text="Price offered per gas unit in base units.",
    )
    publicKey = serializers.CharField(
        required=True,
        help_text="Sender's uncompressed ECDSA secp256k1 public key (128 or 130 hex characters).",
    )
    signature = serializers.CharField(
        required=True,
        help_text="Deterministic ECDSA signature (128 hex characters, optionally 0x-prefixed).",
    )

    def validate_senderAddress(self, value):
        addr = str(value).strip()
        if not ADDRESS_REGEX.match(addr):
            raise serializers.ValidationError("senderAddress must be '0x' followed by 40 hex characters.")
        return addr.lower()

    def validate_receiverAddress(self, value):
        addr = str(value).strip()
        if not ADDRESS_REGEX.match(addr):
            raise serializers.ValidationError("receiverAddress must be '0x' followed by 40 hex characters.")
        return addr.lower()

    def validate_amount(self, value):
        val_str = str(value).strip()
        if not val_str.isdigit() or int(val_str) <= 0:
            raise serializers.ValidationError("amount must be a positive integer in smallest units.")
        return val_str

    def validate_gasPrice(self, value):
        val_str = str(value).strip()
        if not val_str.isdigit() or int(val_str) <= 0:
            raise serializers.ValidationError("gasPrice must be a positive integer.")
        return val_str

    def validate_publicKey(self, value):
        clean_pk = str(value).strip().lower()
        if clean_pk.startswith("04"):
            clean_pk = clean_pk[2:]
        if len(clean_pk) != 128 or not HEX_REGEX.match(clean_pk):
            raise serializers.ValidationError("publicKey must be valid 128 or 130 hex characters.")
        return "04" + clean_pk

    def validate_signature(self, value):
        clean_sig = str(value).strip().lower()
        if clean_sig.startswith("0x"):
            clean_sig = clean_sig[2:]
        if len(clean_sig) != 128 or not HEX_REGEX.match(clean_sig):
            raise serializers.ValidationError("signature must be 128 hex characters (64 bytes raw r+s).")
        return "0x" + clean_sig


class BlockSerializer(serializers.ModelSerializer):
    """
    Serializer for Block entity returning camelCase formatted fields.
    """

    chainId = serializers.IntegerField(source="blockchain.chainId", read_only=True)
    chainName = serializers.CharField(source="blockchain.name", read_only=True)
    parentHash = serializers.CharField(source="previousHash", read_only=True)
    proposerAddress = serializers.SerializerMethodField()

    class Meta:
        from ledger.models import Block
        model = Block
        fields = [
            "id",
            "chainId",
            "chainName",
            "height",
            "blockHash",
            "parentHash",
            "previousHash",
            "merkleRoot",
            "stateRoot",
            "timestamp",
            "proposerAddress",
            "status",
            "transactionCount",
            "gasUsed",
            "blockReward",
            "epoch",
            "round",
            "finalizedAt",
            "createdAt",
        ]

    def get_proposerAddress(self, obj):
        if obj.proposer and getattr(obj.proposer, "account", None):
            return obj.proposer.account.address
        return None


