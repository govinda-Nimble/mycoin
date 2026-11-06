"""
P2P transaction gossip propagation service.
Broadcasts newly accepted transactions to all connected peers asynchronously.
Prevents circular gossip loops using originNodeId tracking and duplicate detection.
"""

import asyncio
import logging
from typing import List, Optional
import httpx
from sqlalchemy import select

from app.core.config import settings
from app.database.session import AsyncSessionLocal
from app.models.node import Node
from app.models.node_peer import NodePeer
from app.schemas.propagation import (
    PeerPropagationStatus,
    PropagatedTransactionPayload,
    PropagationResult,
)
from app.schemas.transaction import SignedTransactionPayload
from app.services.transaction_service import TransactionService

logger = logging.getLogger("myc_node.service.propagation")


class PropagationService:
    """Service handling multi-node transaction gossip and broadcast."""

    @staticmethod
    async def broadcast_transaction(
        payload: SignedTransactionPayload,
        sender_node_id: Optional[str] = None,
        hop_count: int = 0,
    ) -> PropagationResult:
        """
        Broadcasts a transaction to all connected peers of this node.
        Excludes the peer from which the transaction was received (sender_node_id)
        to prevent redundant network echo.
        """
        tx_hash = TransactionService.compute_tx_hash(payload, settings.CHAIN_ID)
        logger.info(
            "Node %s initiating broadcast for tx %s (hopCount=%d, excludedPeer=%s)",
            settings.NODE_ID,
            tx_hash[:10],
            hop_count,
            sender_node_id,
        )

        # 1. Fetch connected peers from local database
        peers_to_notify: List[tuple[str, str]] = []  # (peerNodeId, endpoint)
        async with AsyncSessionLocal() as session:
            peer_stmt = select(NodePeer).where(
                NodePeer.localNodeId == settings.NODE_ID,
                NodePeer.status == "CONNECTED",
            )
            if sender_node_id:
                peer_stmt = peer_stmt.where(NodePeer.peerNodeId != sender_node_id)

            peer_res = await session.execute(peer_stmt)
            active_peers = peer_res.scalars().all()

            for peer in active_peers:
                node_res = await session.execute(
                    select(Node).where(Node.nodeId == peer.peerNodeId)
                )
                node_rec = node_res.scalar_one_or_none()
                if node_rec and node_rec.endpoint:
                    peers_to_notify.append((peer.peerNodeId, node_rec.endpoint))

        if not peers_to_notify:
            logger.info("Node %s has no other connected peers to propagate tx %s", settings.NODE_ID, tx_hash[:10])
            return PropagationResult(
                txHash=tx_hash,
                peersContacted=0,
                peersAccepted=0,
                results=[],
            )

        # 2. Construct propagation payload
        prop_payload = PropagatedTransactionPayload(
            senderAddress=payload.senderAddress,
            receiverAddress=payload.receiverAddress,
            amount=payload.amount,
            nonce=payload.nonce,
            gasLimit=payload.gasLimit,
            gasPrice=payload.gasPrice,
            publicKey=payload.publicKey,
            signature=payload.signature,
            originNodeId=settings.NODE_ID,
            hopCount=hop_count + 1,
        )

        # 3. Asynchronously dispatch gossip to each peer
        async def send_to_peer(peer_node_id: str, endpoint: str) -> PeerPropagationStatus:
            clean_endpoint = endpoint.rstrip("/")
            url = f"{clean_endpoint}/api/v1/transactions/receive"
            try:
                async with httpx.AsyncClient(timeout=settings.PEER_TIMEOUT_SECONDS) as client:
                    res = await client.post(
                        url,
                        json=prop_payload.model_dump(),
                        headers={"X-Network-Key": settings.NETWORK_KEY},
                    )
                    if res.status_code in (200, 201):
                        data = res.json()
                        res_status = data.get("status", "ACCEPTED")
                        return PeerPropagationStatus(
                            peerNodeId=peer_node_id,
                            endpoint=clean_endpoint,
                            status=res_status,
                        )
                    return PeerPropagationStatus(
                        peerNodeId=peer_node_id,
                        endpoint=clean_endpoint,
                        status="FAILED",
                        error=f"HTTP {res.status_code}: {res.text}",
                    )
            except Exception as exc:
                logger.warning("Propagation to peer %s (%s) failed: %s", peer_node_id, clean_endpoint, exc)
                return PeerPropagationStatus(
                    peerNodeId=peer_node_id,
                    endpoint=clean_endpoint,
                    status="FAILED",
                    error=str(exc),
                )

        tasks = [send_to_peer(pid, ep) for pid, ep in peers_to_notify]
        statuses: List[PeerPropagationStatus] = await asyncio.gather(*tasks)

        accepted_count = sum(1 for s in statuses if s.status in ("ACCEPTED", "ALREADY_KNOWN"))
        logger.info(
            "Node %s completed broadcast for tx %s: %d/%d peers acknowledged",
            settings.NODE_ID,
            tx_hash[:10],
            accepted_count,
            len(statuses),
        )

        return PropagationResult(
            txHash=tx_hash,
            peersContacted=len(statuses),
            peersAccepted=accepted_count,
            results=statuses,
        )

