"""
SQLAlchemy 2.x model representing a node's local in-memory/persistent Mempool.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Mempool(Base, TimestampMixin):
    """
    Independent local Mempool tracking unconfirmed transactions on this node.
    Transactions are prioritized by gasPrice / fee for block production.
    """

    __tablename__ = "mempool"

    txHash: Mapped[str] = mapped_column(
        String(66),
        unique=True,
        nullable=False,
        index=True,
        doc="Cryptographic SHA-256 hash reference of the transaction",
    )
    senderAddress: Mapped[str] = mapped_column(
        String(42),
        nullable=False,
        index=True,
        doc="Sender wallet address",
    )
    receiverAddress: Mapped[str] = mapped_column(
        String(42),
        nullable=False,
        doc="Receiver wallet address",
    )
    amount: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        doc="Transfer amount in base units",
    )
    fee: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        doc="Calculated transaction fee (gasLimit * gasPrice) in base units",
    )
    priority: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        index=True,
        doc="Fee-based ordering score for block candidate selection (higher is prioritized)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        index=True,
        doc="Mempool status: PENDING, SELECTED, EXPIRED",
    )
    addedAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        doc="Timestamp when transaction entered this node's mempool",
    )
    expiresAt: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Optional TTL timestamp after which transaction is evicted from mempool",
    )

    def __repr__(self) -> str:
        return f"<Mempool(txHash='{self.txHash[:10]}...', fee='{self.fee}', priority={self.priority}, status='{self.status}')>"

