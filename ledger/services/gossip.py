"""
P2P Gossip service for propagating signed transactions and reconciling blocks
across node mempools.
"""

import logging
from typing import Any, Dict, List, Optional

from django.db import transaction
from ledger.models import Block, BlockStatus, MempoolStatus, MempoolTransaction, Transaction, TransactionStatus
from ledger.services.transaction_validator import (
    TransactionValidationError,
    validate_and_enqueue_transaction,
)
from network.models import Node, NodePeer, PeerStatus

logger = logging.getLogger(__name__)


def gossip_transaction_to_peers(
    payload: Dict[str, Any],
    source_node: Node,
) -> Dict[str, Any]:
    """
    Gossips original signed transaction payload to all connected outbound peers of source_node.
    Each peer independently validates and enqueues the transaction into its own mempool.

    Args:
        payload: Original signed transaction dictionary.
        source_node: The Node that received or generated the transaction.

    Returns:
        Dictionary mapping peer nodeId to outcome ('accepted', 'duplicate', 'rejected', 'error').
    """
    peers = NodePeer.objects.filter(
        localNode=source_node,
        status=PeerStatus.CONNECTED,
    ).select_related("peerNode")

    results: Dict[str, Any] = {}

    for peer_link in peers:
        peer_node = peer_link.peerNode
        try:
            res = validate_and_enqueue_transaction(payload, node=peer_node)
            results[peer_node.nodeId] = {
                "status": "accepted",
                "txHash": res.tx_hash,
                "message": res.message,
            }
        except TransactionValidationError as err:
            if "already active" in err.message or "already recorded" in err.message:
                results[peer_node.nodeId] = {
                    "status": "duplicate",
                    "step": err.step,
                    "message": err.message,
                }
            elif "Nonce conflict" in err.message:
                results[peer_node.nodeId] = {
                    "status": "competing_rejected",
                    "step": err.step,
                    "message": err.message,
                }
            else:
                results[peer_node.nodeId] = {
                    "status": "rejected",
                    "step": err.step,
                    "message": err.message,
                }
        except Exception as exc:
            logger.error("Failed to gossip transaction to peer %s: %s", peer_node.nodeId, exc)
            results[peer_node.nodeId] = {
                "status": "error",
                "message": str(exc),
            }

    return results


def reconcile_block_with_node_mempool(node: Node, block: Block) -> Dict[str, int]:
    """
    Reconciles an individual node's local mempool against a finalized block.
    Removes included transactions, marks losing competing transactions as REPLACED,
    and evicts transactions whose nonces have become outdated.

    Args:
        node: The Node instance whose mempool is to be reconciled.
        block: The finalized Block instance.

    Returns:
        Dictionary with counts of included, replaced, and expired mempool transactions.
    """
    if block.status != BlockStatus.FINALIZED:
        logger.warning("Attempted to reconcile mempool against non-finalized block #%d.", block.height)
        return {"included": 0, "replaced": 0, "expired": 0}

    included_count = 0
    replaced_count = 0
    expired_count = 0

    with transaction.atomic():
        block_txs = list(
            block.block_transactions.select_related("transaction__sender").all()
        )

        for btx in block_txs:
            tx = btx.transaction
            sender = tx.sender

            # Mark this transaction as INCLUDED in node's mempool
            updated = MempoolTransaction.objects.filter(
                node=node,
                transaction=tx,
            ).exclude(status=MempoolStatus.INCLUDED).update(status=MempoolStatus.INCLUDED)
            included_count += updated

            # Mark competing transactions with same sender and nonce as REPLACED in node mempool
            competing_qs = MempoolTransaction.objects.filter(
                node=node,
                transaction__sender=sender,
                transaction__nonce=tx.nonce,
            ).exclude(transaction=tx)
            replaced = competing_qs.filter(status=MempoolStatus.ACTIVE).update(status=MempoolStatus.REPLACED)
            if replaced > 0:
                replaced_count += replaced
            else:
                replaced_count += competing_qs.filter(status=MempoolStatus.REPLACED).count()

            # Invalidate any mempool entries with nonces below the sender's finalized nonce
            expired = MempoolTransaction.objects.filter(
                node=node,
                transaction__sender=sender,
                transaction__nonce__lt=sender.nonce,
                status=MempoolStatus.ACTIVE,
            ).update(status=MempoolStatus.EXPIRED)
            expired_count += expired

    return {
        "included": included_count,
        "replaced": replaced_count,
        "expired": expired_count,
    }
