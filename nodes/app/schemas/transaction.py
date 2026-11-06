"""
Pydantic v2 schemas for transaction ingestion, responses, and verification payloads.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignedTransactionPayload(BaseModel):
    """
    Standard signed transaction payload produced by the wallet signing service
    and broadcast to blockchain nodes.
    """
    senderAddress: str = Field(..., description="Sender wallet address (0x + 40 hex)")
    receiverAddress: str = Field(..., description="Receiver wallet address (0x + 40 hex)")
    amount: str = Field(..., description="Transfer amount in base MYC units")
    nonce: int = Field(default=0, ge=0, description="Sequential account nonce")
    gasLimit: int = Field(default=21000, gt=0, description="Gas limit")
    gasPrice: str = Field(default="2", description="Gas price")
    publicKey: str = Field(..., description="Uncompressed 130-char ECDSA public key")
    signature: str = Field(..., description="0x-prefixed ECDSA signature (130-132 hex chars)")

    @field_validator("senderAddress", "receiverAddress")
    @classmethod
    def validate_address_format(cls, v: str) -> str:
        clean = v.strip().lower()
        if not (clean.startswith("0x") and len(clean) == 42):
            raise ValueError(f"Invalid address format: '{v}'. Must be '0x' followed by 40 hex characters.")
        return clean

    @field_validator("amount")
    @classmethod
    def validate_amount_format(cls, v: str) -> str:
        clean = v.strip()
        if not clean.isdigit() or int(clean) <= 0:
            raise ValueError("Amount must be a positive integer in base units.")
        return clean


class TransactionResponse(BaseModel):
    """Full transaction representation stored on the node."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    txHash: str
    senderAddress: str
    receiverAddress: str
    amount: str
    nonce: int
    gasLimit: int
    gasPrice: str
    publicKey: str
    signature: str
    status: str
    receivedAt: datetime
    confirmedAt: Optional[datetime] = None
    blockHeight: Optional[int] = None


class TransactionStatusResponse(BaseModel):
    """Lightweight transaction query response."""
    txHash: str
    status: str
    senderAddress: str
    receiverAddress: str
    amount: str
    blockHeight: Optional[int] = None
    receivedAt: datetime

