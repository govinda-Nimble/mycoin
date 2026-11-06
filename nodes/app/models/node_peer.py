"""
SQLAlchemy 2.x model representing peer relationships between nodes.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class NodePeer(Base, TimestampMixin):
    """
    NodePeer model tracking peer connections of the local node.
    Maintains independent peer lists in each node's isolated database.
    """

    __tablename__ = "node_peers"

    localNodeId: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Local node identity holding this peer relationship",
    )
    peerNodeId: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Identity of the remote connected peer node",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        doc="Peer connection status: PENDING, CONNECTED, DISCONNECTED",
    )
    lastConnectedAt: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of the most recent successful connection or heartbeat",
    )

    __table_args__ = (
        UniqueConstraint("localNodeId", "peerNodeId", name="uq_local_peer_pair"),
        CheckConstraint("localNodeId != peerNodeId", name="ck_prevent_self_peering"),
    )

    def __repr__(self) -> str:
        return f"<NodePeer(local='{self.localNodeId}', peer='{self.peerNodeId}', status='{self.status}')>"

