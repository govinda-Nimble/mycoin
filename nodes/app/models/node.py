"""
SQLAlchemy 2.x model representing a Node in the MYC Blockchain Network.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class Node(Base, TimestampMixin):
    """
    Node model representing local node identity and known peers in the network.
    """

    __tablename__ = "nodes"

    nodeId: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique stable node identity, e.g. myc-node-001",
    )
    nodeType: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="FULL",
        doc="Node type: FULL or VALIDATOR",
    )
    endpoint: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Base HTTP endpoint for node communication, e.g. http://localhost:8001",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ONLINE",
        doc="Current node operational status: ONLINE or OFFLINE",
    )
    lastHeartbeat: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of the most recent heartbeat recorded",
    )
    protocolVersion: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="v1.0.0",
        doc="Communication protocol version",
    )
    p2pPublicKey: Mapped[str] = mapped_column(
        String(130),
        nullable=False,
        doc="Hex-encoded ECDSA uncompressed public key (128-130 hex chars)",
    )

    def __repr__(self) -> str:
        return f"<Node(nodeId='{self.nodeId}', nodeType='{self.nodeType}', status='{self.status}', endpoint='{self.endpoint}')>"

