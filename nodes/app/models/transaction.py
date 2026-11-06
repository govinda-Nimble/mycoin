"""
SQLAlchemy 2.x model representing a verified blockchain Transaction on a node.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Transaction(Base, TimestampMixin):
    """
    Transaction model representing on-chain transfer requests.
    Persisted independently on each node upon receipt and verification.
    """

    __tablename__ = "transactions"

    txHash: Mapped[str] = mapped_column(
        String(66),
        unique=True,
        nullable=False,
        index=True,
        doc="Cryptographic SHA-256 hash of canonical payload and signature, prefixed with 0x",
    )
    senderAddress: Mapped[str] = mapped_column(
        String(42),
        nullable=False,
        index=True,
        doc="Sender wallet address (0x + 40 hex chars)",
    )
    receiverAddress: Mapped[str] = mapped_column(
        String(42),
        nullable=False,
        index=True,
        doc="Receiver wallet address (0x + 40 hex chars)",
    )
    amount: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        doc="Monetary transfer amount in base MYC units (string to preserve exact precision)",
    )
    nonce: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Sequential account nonce for replay prevention",
    )
    gasLimit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=21000,
        doc="Maximum gas allowed for this transfer",
    )
    gasPrice: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="2",
        doc="Offered price per unit of gas",
    )
    publicKey: Mapped[str] = mapped_column(
        String(130),
        nullable=False,
        doc="Hex-encoded uncompressed ECDSA public key of sender",
    )
    signature: Mapped[str] = mapped_column(
        String(132),
        nullable=False,
        doc="ECDSA secp256k1 deterministic signature ('0x' + 128 hex chars)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        index=True,
        doc="Transaction lifecycle: PENDING, MEMPOOL, PROPAGATING, CONFIRMED, FAILED",
    )
    receivedAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        doc="Timestamp when this node received and verified the transaction",
    )
    confirmedAt: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the transaction was included into a finalized block",
    )
    blockHeight: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Height of the block containing this transaction",
    )

    def __repr__(self) -> str:
        return f"<Transaction(txHash='{self.txHash[:10]}...', sender='{self.senderAddress[:8]}...', amount='{self.amount}', status='{self.status}')>"

